# Contract360 — Complete Pipeline Walkthrough

---

## System Overview

Contract360 is a multi-contract RAG system with three main subsystems:

1. **Ingestion pipeline** — uploads, parses, embeds, indexes, and builds a knowledge graph for each contract
2. **Query pipeline** — routes questions through tree search, graph traversal, or a hybrid of both; streams answers back with citations and follow-up suggestions
3. **Session and storage layer** — persists chat history, contract artifacts, and the knowledge graph across Azure services

---

## Infrastructure Dependencies

| Service | Purpose |
|---|---|
| Azure Blob Storage | Raw uploaded files + all contract artifacts (tree, chunks, index docs, summary, KG) |
| Azure AI Search | Vector + BM25 hybrid search over embedded contract chunks |
| Azure OpenAI | Embeddings (`text-embedding-3-small`, 1536 dims) + chat completions (`gpt-4o` or configured deployment) |
| Cosmos DB NoSQL | Chat session history, ingest job tracking |
| Cosmos DB Gremlin | Knowledge graph (two-tier: mention nodes + canonical entity vertices) |
| Azure Document Intelligence | Optional high-quality PDF parsing (fallback: PyMuPDF) |
| PageIndex API | Optional hierarchical tree builder (fallback: regex heuristic) |

---

## 1. Application Startup

On startup, the FastAPI `lifespan` handler calls `config.validate_required_config()`.
This checks that all seven critical Azure env vars are populated:
`AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_ADMIN_KEY`,
`COSMOS_NOSQL_ENDPOINT`, `COSMOS_NOSQL_KEY`, `AZURE_BLOB_CONNECTION_STRING`.
If any are missing, the process exits immediately with a clear list rather than crashing later mid-request.

CORS origins are read from the `ALLOWED_ORIGINS` env var (comma-separated). Defaults to
`localhost:5173` and `localhost:3000` for local development; set to the deployed frontend URL in production.

---

## 2. Document Ingestion Pipeline

### 2a. API entry point (`POST /ingest`)

The frontend sends a `multipart/form-data` request with one or more files.
The API layer does the following synchronously before returning `HTTP 202`:

1. Validates file extension (`.pdf`, `.txt`, `.md`) and size (50 MB cap)
2. Derives `contractId` from the filename — strips extension, replaces spaces and special characters with underscores
3. Creates a job record in Cosmos DB (`ingest_jobs` container): `status: queued`, `stage: uploading`, `progress: 0`
4. Uploads raw bytes to Azure Blob at `uploads/<userId>/<jobId>/<filename>`
5. Submits `_run_job()` to a `ThreadPoolExecutor` and returns immediately — the caller gets `{jobId, contractId, status: "queued"}` right away

The frontend polls `GET /ingest/{jobId}/status` every 2.5 seconds, reading `stage` and `progress` to animate the upload panel.

---

### 2b. Background worker (`app/ingestion/worker.py`)

The worker runs the following stages in sequence, updating `stage` and `progress` in Cosmos after each:

#### Stage 1 — Download (`progress: 5`)
Fetches raw bytes from Azure Blob. Writes to a `tempfile.mkstemp()` path — ephemeral, never written to a permanent local path.

#### Stage 2 — Parse (`progress: 15`)
`DocumentReader` dispatches to:
- **Azure Document Intelligence** (`USE_AZURE_DOCUMENT_INTELLIGENCE=true`) — high-quality layout-aware extraction
- **PyMuPDF fallback** — page-by-page text extraction

Produces raw text + page-number metadata per page.

#### Stage 3 — Tree building (`progress: 30`)
Produces a hierarchical `TreeNode` tree (`nodeId`, `nodeType`, `title`, `text`, `parentNodeId`, `children[]`).
Two paths:
- **PageIndex API** (`USE_PAGEINDEX_API=true`) — REST call to an external API that returns a structured document tree; polls until ready; uploads `tree.json` to Blob
- **Fallback tree builder** — regex-based heuristic detection of articles, sections, and clauses; builds the same `TreeNode` dataclass structure

Both paths write `tree.json` to `artifacts/<contractId>/` in Blob. The tree is the structural spine used by retrieval at query time.

#### Stage 4 — Chunking (`progress: 50`)
`create_chunks()` flattens the tree depth-first, skips non-content node types (`document`, `article`), and applies:
- Sliding window: 850 words per chunk, 80-word overlap between consecutive chunks
- `clauseType` inferred from keyword matching on clause titles (`termination`, `payment`, `liability`, `indemnity`, `compliance`, etc.)
- Each chunk carries `nodeId`, `kgId` (graph bridge key), `sectionTitle`, `sourcePath`, `pageStart`, `pageEnd`

#### Stage 5 — Batch embedding (`progress: 65`)
`EmbeddingClient.embed_many()` sends texts to Azure OpenAI `text-embedding-3-small` (1536 dimensions) in batches of 16 (the Azure API limit). A 100-chunk contract makes 7 API calls instead of 100.

Builds `index_docs` — one document per chunk with all search fields plus the `embedding` float array.

#### Stage 6 — Document summary (`progress: 70`)
`generate_summary()` sends the first 16k characters of raw text to the chat model in a single LLM call.
Output is a structured JSON:
```
{purpose, parties, effectiveDate, term, keyObligations,
 paymentSummary, terminationSummary, complianceTopics}
```
Saved as `summary.json` to `artifacts/<contractId>/` in Blob.
At query time, summary questions bypass all retrieval and return this pre-generated answer at zero cost.

#### Stage 7 — Artifact persistence (`progress: 75`)
`BlobArtifactStore.save_contract_artifacts()` uploads to `artifacts/<contractId>/` in Blob:
`tree.json`, `chunks.json`, `index_docs.json`, `manifest.json`

#### Stage 8 — Azure AI Search upload (`progress: 80`)
`AzureSearchIndexer.upload_documents()` batches `index_docs` in groups of 500.
Each document in the index carries:

| Field | Description |
|---|---|
| `contractId` | Contract identifier |
| `nodeId` | Tree node this chunk came from |
| `kgId` | Bridge key linking to the Gremlin graph vertex |
| `graphReady` | Bool — true once KG pipeline completes |
| `embedding` | float[1536] — used for vector search |
| `sectionTitle` | Parent section heading |
| `clauseType` | Inferred clause category |
| `pageStart` / `pageEnd` | Page range |
| `sourcePath` | Breadcrumb path in the document tree |
| `text` | Chunk text |

#### Stage 9 — Knowledge graph pipeline (`progress: 82–90`)
Runs automatically if Gremlin is configured (`GREMLIN_ENDPOINT`, `GREMLIN_USERNAME`, `GREMLIN_PASSWORD` all set).

**Extraction** (`progress: 82`)

`select_representative_clauses()` selects all content clauses from the normalized tree (no top-N cap, `limit=None`).

For each clause, `LegalLLMExtractor.extract_from_clause()` makes one LLM call with a structured extraction prompt.
Output per clause: a JSON object with typed entity lists — `Obligation`, `Right`, `Restriction`, `Party`, `Indemnitor`/`Indemnitee`, `TerminationEvent`, `BreachEvent`, `NoticeRequirement`, `PaymentObligation`, `LiabilityCap`, `Deadline` — plus edges connecting them (`OWED_BY`, `OWED_TO`, `INDEMNIFIES`, `HAS_DEADLINE`, `TRIGGERS`, etc.).
Each entity carries `clauseTitle`, `pageStart`, `pageEnd` denormalized onto it (no structural clause vertex needed at query time).

**Resolution pipeline** (`progress: 90`) — `resolve_one_contract(contract_id, tenant_id, extraction_dicts)` runs three stages:

1. **OntologyNormalizer** — maps raw LLM-generated labels to the canonical 40-type ontology (e.g. normalizes `"obligation"` / `"Obligation"` / `"contractual_obligation"` to the canonical `Obligation` label)

2. **EntityResolver** — merges duplicate mentions of the same entity within the contract (e.g. "Con Edison", "Con Edison Company of New York", "the Company" all referring to the same party → one merged node with a deterministic `kgId`). Deduplicates edges.

3. **Canonicalizer** — links resolved mention nodes to cross-contract `CanonicalEntity` vertices. Builds `RESOLVED_AS` edges: `mention_node → CanonicalEntity`. This is what enables portfolio-wide queries like "all obligations where Con Edison is the obligor across every contract".

**Graph write** — `write_resolved_graph()` upserts to Cosmos Gremlin via `GremlinWriter`:

- **Tier 1 (mention layer)** — one vertex per resolved entity (`Obligation`, `Right`, `Party`, etc.) with citation metadata (`clauseTitle`/`pageStart`/`pageEnd`) on the vertex itself. Partition key: `TENANT_ID`.
- **Tier 2 (canonical layer)** — one `CanonicalEntity` vertex per unique real-world entity (e.g. one for "Con Edison" shared across all contracts). Connected to its mention nodes via `RESOLVED_AS` edges.

Idempotent: vertex IDs are deterministic (`<contractId>:<entityType>:<slug>`), so re-ingesting a contract upserts rather than duplicates.

`graphReady` flag on Search documents is not updated by the current worker (it's set to `false` at index time); the `_graph_available()` check in the query service reads from Gremlin directly.

#### Stage 10 — Job completion (`progress: 100`, `status: done`)
`JobStore.mark_done()` writes final status to Cosmos.
The frontend polling loop picks this up, closes the poller for this job, and calls `refreshContracts()` to add the new contract to the sidebar.

---

## 3. Query Pipeline

**Entry points:**
- `POST /sessions/{session_id}/ask` — returns full JSON response
- `POST /sessions/{session_id}/ask/stream` — returns SSE stream (used by the frontend)

Request body: `{question, route_override: "auto", contract_ids: [...], top: 4}`

---

### Step 0 — Chat history

`SessionService.save_user_message()` appends the question to the session's `messages` array in Cosmos via `replace_item`.

`SessionService.build_llm_history()` fetches all messages for the session, slices the last 12 (6 turns × 2), and returns `[{"role": "user"|"assistant", "content": "..."}]` for injection into the LLM prompt.

---

### Step 0.5 — Summary shortcut (zero retrieval, zero LLM cost)

`_is_summary_query()` checks the question against a set of exact phrase patterns:
"summarize this contract", "what is this contract about?", "give me an overview", etc.

If matched **and** a `summary.json` exists in Blob for the active contract → `format_summary_as_answer()` formats the pre-generated summary as markdown and returns immediately. No routing, no retrieval, no LLM call.

---

### Step 1 — Contract scope resolution (`contract_resolver.py`)

Before routing, the effective contract scope is narrowed if the question names a specific contract.

- **Candidate pool** = `contract_ids` from the UI selection (checkboxes), or a single `contractId` from the session filter, or the full indexed portfolio (if nothing selected)
- `resolve_scope()` tokenizes both the question and each candidate contract ID, removes stopwords (`agreement`, `contract`, `service`, `inc`, years, etc.), and finds candidates whose distinctive tokens overlap with the question
- If the question says "...in the Edison contract" and three contracts are selected, scope narrows to just the Edison one
- Falls back to the full candidate pool if no match — never narrows to nothing

---

### Step 2 — LLM query routing (`query_router.py`)

A single `AzureOpenAI.chat.completions.create()` call (`temperature=0`, `max_tokens=200`) with a system prompt describing the three routes.

Input: last 4 chat turns + current question.

Output (parsed JSON):
```json
{
  "route": "tree" | "graph" | "hybrid",
  "reasoning": "one sentence",
  "rewritten_query": "pronouns resolved, context folded in",
  "structural_scope": {"type": "Article", "identifier": "XII"} | null
}
```

Route selection logic in the prompt:
- **`tree`** — text lookup, summarization, structural navigation ("what does section 5.2 say?", "explain the indemnification clause")
- **`graph`** — structured fact questions about parties, obligations, deadlines, rights ("what does Con Edison owe?", "which obligations have deadlines?")
- **`hybrid`** — needs both clause text AND graph facts, or any comparison/contrast question ("compare termination clauses between both contracts", "what are the environmental obligations with citations?")

Comparison terms (`compare`, `versus`, `differ`, `contrast`, `stricter`, `side by side`) always route to `hybrid`.

**Fallback:** if the LLM call fails or returns malformed JSON → `_keyword_route()` keyword classifier using the same term lists.

**Graph availability check:** if `route` is `graph` or `hybrid` but no graph exists for the in-scope contracts, route is silently downgraded to `tree`.

---

### Step 3 — Retrieval

All retrieval uses `rewritten_query` (not the original question).

---

#### Tree route — `_tree_retrieve()`

`AzureSearchTester.hybrid_search()`:
- Embeds `rewritten_query` via `EmbeddingClient.embed()`
- Sends a `VectorizedQuery` (k=30 nearest neighbours on the `embedding` field) **combined** with BM25 full-text search (Azure AI Search hybrid mode)
- OData filter: `contractId eq 'X'` for single contract, `contractId eq 'A' or contractId eq 'B'` for multi

If `structural_scope` is set (e.g. Article XII): switches to `retrieve_structural_scope()` which applies an additional filter on `sectionTitle` matching the article identifier.

Results are enriched by `SemanticRetriever.retrieve()`:
- Loads `tree.json` from Blob for the contract (module-level `_TREE_CACHE` keyed by `contractId` — downloaded once per process lifetime, no repeated Blob calls)
- For each search hit, calls `expand_context(nodeId)` which adds: the parent node (full section context), sibling nodes (neighboring clauses), and child nodes (sub-clauses)
- Returns chunks annotated with `contextExpansion` — neighbouring tree nodes give the LLM surrounding context beyond the matched chunk

---

#### Graph route — `_graph_retrieve()`

Two-phase approach:

**Phase 1 — Canonical entity-anchored (preferred path):**

`canonical_graph_retrieve()` in `graph_canonical.py`:

1. `CanonicalGraphRetriever._canonicals()` fetches all `CanonicalEntity` vertices from Gremlin (cached per retriever instance)
2. `link_entities()` finds entities mentioned in the question using span-aware longest-match — "con edison" claims its span before a shorter alias of a different entity could match
3. For each linked canonical entity: traverses `RESOLVED_AS` edges → mention nodes → follows `OWED_BY` edges for obligations the party owes, `OWED_TO` for obligations owed to the party
4. Returns structured fact blocks per entity with full cross-contract reach

**Phase 2 — Vector-anchored fallback (when no canonical entity found):**

If Phase 1 returns nothing:
- Calls `_make_search_anchor()` which runs a vector search to find relevant clause IDs
- `subgraph_from_clauses()` queries Gremlin for `Obligation`, `Right`, `Restriction`, `Event` vertices that have a `sourceClauseId` matching those clause IDs
- Returns graph facts anchored to semantically relevant clauses

**Semantic intent classification (for `graph_native_retrieve`):**

At module startup, `_classify_intent` embeds 13 intent descriptions + example questions (cached in `_intent_embeddings`, populated once). At query time:
- Embeds the question (one API call)
- Computes cosine similarity against all 13 cached intent vectors
- Returns the closest intent: `indemnity`, `termination`, `breach_cure`, `notice`, `payment`, `liability`, `deadline`, `rights`, `restrictions`, `all_obligations`, `obligations_by_party`, `obligations_owed_to_party`, `cross_contract`
- `_intent_to_fetcher()` maps intent → the right `GraphNativeRetriever` Gremlin method
- No keyword matching anywhere — "who bears the financial risk if something goes wrong?" correctly resolves to `indemnity`

Falls back to `graph_native_retrieve()` (legacy template-based retriever) if the canonical phase returns nothing.

---

#### Hybrid route — `_hybrid_retrieve()`

Runs both:
1. `_tree_retrieve()` → clause text context; all tree citations re-labelled `route="hybrid"`
2. `_graph_retrieve()` → structured graph facts + graph citations

Merges both context blocks into a single prompt string separated by `===` headers. Produces citations from both sources.

---

#### Comparison queries (2+ contracts selected, comparison intent detected)

`_is_comparison()` fires before intent classification in `graph_native_retrieve()`:
- If triggered: `_classify_intent()` identifies the topic being compared
- Fetches that topic's facts for all in-scope contracts
- `format_comparison_result()` builds an explicit `CONTRACT A (id) / CONTRACT B (id)` side-by-side block with embedded instructions to the LLM ("Produce a side-by-side answer, NOT sequential summaries")
- `get_shared_parties()` appends parties appearing in multiple contracts as enrichment

---

### Step 4 — Answer grounding and generation (`_ground_and_generate()`)

1. **Rank citations** by confidence score descending
2. **Append a SOURCES block** to the retrieval context:
   ```
   [S1] Clause Title — Contract Name (pp. X-Y)
   [S2] ...
   ```
3. **LLM call** — `AnswerGenerator.generate()`:
   - Messages: `[system_prompt] + [last 12 chat history] + [user message with context]`
   - `temperature=0`, `max_tokens=1500`
   - System prompt instructs the model to cite `[S#]` inline, group by theme, write in executive Markdown, use Markdown numbered lists (one item per line), begin with a direct answer
   - For comparison questions: instructs `**[Dimension]** / Contract A: ... / Contract B: ...` structure with a Key Differences summary paragraph
   - LLM must respond with valid JSON: `{"answer": "...", "follow_up_suggestions": ["...", "...", "..."]}`
4. **Extract cited sources** — regex finds all `[S#]` in the answer, returns only those citation cards in order of first appearance. Falls back to top-8 ranked citations if none cited.
5. **Strip markers** — `[S#]` markers removed from the displayed answer text
6. Returns `(clean_answer, follow_up_suggestions, grounded_citations)`

---

### Step 5 — SSE streaming (`/ask/stream`)

The entire `answer_question()` call runs in `asyncio.get_event_loop().run_in_executor(None, ...)` — blocking sync code runs in a thread pool without blocking the async event loop.

Once the answer string is ready, the SSE generator yields:

```
{"type": "delta", "content": "word "}   ← one per word
{"type": "delta", "content": "next "}
...
{"type": "done", "message_id": "...", "route": "...", "reason": "...",
                 "citations": [...], "follow_up_suggestions": [...]}
```

`StreamingResponse(media_type="text/event-stream")` with `X-Accel-Buffering: no` disables nginx proxy buffering so words reach the browser immediately.

The frontend `streamAsk()` in `client.ts` reads the stream via `fetch` + `ReadableStream`, splits on newlines, parses each JSON event:
- `onDelta(token)` — appends each word to the streaming message bubble in real time
- `onDone(event)` — replaces the streaming placeholder with the final message, attaches citation cards and follow-up suggestion chips

---

### Step 6 — Persist assistant message

`SessionService.save_assistant_message()` appends to the session's `messages` array in Cosmos:
```json
{
  "id": "<uuid>",
  "role": "assistant",
  "content": "<answer>",
  "route": "hybrid",
  "sources": [...citations],
  "follow_up_suggestions": ["...", "...", "..."],
  "timestamp": "..."
}
```

Sets `previewText` (first 120 chars of the answer) on the session for sidebar display.
Auto-titles the session from the first user question if the title is still "New Session".

`follow_up_suggestions` are stored per message and restored when `GET /sessions/{id}/history` is called, so chips reappear when switching back to an old session.

---

## 4. Cross-Contract Comparison Query — Full Flow

User selects two contracts in the sidebar, types: *"How do the termination clauses differ between these two contracts?"*

1. `resolve_scope()` confirms both contracts are in the candidate pool; question doesn't name just one, so scope stays as both
2. Router classifies as `hybrid` (comparison intent; "differ" triggers comparison path)
3. `_graph_retrieve()` → `canonical_graph_retrieve()` detects `_is_comparison()=true`, delegates to `graph_native_retrieve()`
4. In `graph_native_retrieve()`: `_is_comparison()` fires first; `_classify_intent()` scores "termination" as closest intent (cosine similarity against the 13 intent descriptions)
5. `_intent_to_fetcher("termination")` → `retriever.get_termination_facts(contract_ids=[A, B])`
6. Facts are grouped by `contractId` → `{A: [...], B: [...]}`
7. `format_comparison_result()` builds:
   ```
   CONTRACT A (Edison_NYPA_OandM_Contract_1)
   ──────────────────────────────────────────
   1. [TerminationEvent] Termination for Cause ...
      Source: Article 12 (pp. 34-36)
   ...
   CONTRACT B (SoCal_EPC)
   ──────────────────────
   1. [TerminationEvent] ...
   ```
   with embedded instructions: "Produce a side-by-side answer, NOT sequential summaries"
8. Shared parties across both contracts appended as enrichment
9. `_tree_retrieve()` runs in parallel and appends clause text evidence
10. `_ground_and_generate()` sends the combined context + SOURCES list to the LLM
11. LLM outputs dimension-by-dimension comparison (e.g. "**Grounds for Termination**", "**Notice Period**", "**Cure Period**") with Key Differences summary
12. Only cited `[S#]` sources returned as citation cards; markers stripped from answer
13. Answer streamed word-by-word via SSE; follow-up suggestions appended in `done` event

---

## 5. Contract Delete Pipeline

**Entry point:** `DELETE /contracts/{contractId}`

`delete_contract()` in `app/services/contract_delete.py` deletes best-effort from three stores:

1. **Azure AI Search** — `AzureSearchTester.delete_by_contract()` pages through documents filtered by `contractId eq '...'`, deletes in batches of 1000
2. **Cosmos Gremlin** — drops all vertices (and their incident edges) where `contractId` matches
3. **Azure Blob** — `BlobStore.delete_contract_artifacts()` deletes everything under `artifacts/<contractId>/`

Returns a per-store summary `{search: n, gremlin: n, blob: n}`. Partial failures are reported, not raised — the UI shows which stores succeeded.

The frontend confirms with the user ("This cannot be undone"), then removes the contract from the sidebar state immediately on success.

---

## 6. Chat Session Management

**Storage:** Cosmos DB NoSQL, container `chat_sessions`, partition key `/userId`

**Session document structure:**
```json
{
  "id": "<uuid>",
  "userId": "<user>",
  "title": "auto-generated from first question",
  "contractFilter": "<contractId> | null",
  "createdAt": "ISO-8601",
  "updatedAt": "ISO-8601",
  "previewText": "first 120 chars of last assistant message",
  "messages": [
    {
      "id": "<uuid>",
      "role": "user" | "assistant",
      "content": "...",
      "route": "hybrid",
      "sources": [...],
      "follow_up_suggestions": [...],
      "timestamp": "..."
    }
  ]
}
```

`GET /sessions` — projection query (`SELECT c.id, c.title, c.contractFilter, c.createdAt, c.updatedAt, c.previewText`) — **never fetches the messages array** for efficient sidebar loading.

`GET /sessions/{id}/history` — fetches the full document, returns the messages array. Called lazily only when a session is selected in the sidebar.

`build_llm_history()` slices the last `HISTORY_TURNS * 2 = 12` messages, maps to `{"role", "content"}` dicts. The current user message is excluded from history (already in the main prompt).

---

## 7. Frontend Architecture

### State (`App.tsx`)

| State | Type | Description |
|---|---|---|
| `sessions` | `ChatSession[]` | Loaded from `GET /sessions` on mount |
| `activeSessionId` | `string \| null` | Triggers lazy history load |
| `contracts` | `Contract[]` | Merged from ingest jobs + Search index |
| `selectedContracts` | `string[]` | Sidebar checkboxes; empty = portfolio-wide |
| `activeUploads` | `number` | Count of in-progress jobs; drives sidebar badge |

### Contract list refresh

`refreshContracts` is a `useCallback` that merges two sources:
- `GET /ingest` — ingest job records (tracks UI-uploaded contracts)
- `GET /contracts` — Azure AI Search contract list (picks up CLI-ingested contracts too)

Runs on mount and whenever `activeUploads` drops (a job just finished).

A 4-second polling loop tracks active jobs, updates `activeUploads`, and calls `refreshContracts()` whenever a job completes.

### Message flow (`handleSendMessage`)

1. Creates a session if none exists (`POST /sessions`)
2. Appends the user message and a streaming placeholder (`isStreaming: true, content: ""`) to local state — UI is responsive immediately
3. Calls `api.streamAsk()` which reads SSE via `fetch` + `ReadableStream`
4. `onDelta(word)` — appends each word to the streaming bubble
5. `onDone(event)` — replaces the placeholder with the final message; attaches:
   - **Route badge** — color-coded by route (`tree`=amber, `graph`=emerald, `hybrid`=violet, `summary`=sky)
   - **Citation cards** — contract name, clause title, page range, evidence quote
   - **Follow-up suggestion chips** — clickable, call `onSendMessage` directly

### Upload flow (`UploadPanel.tsx`)

- Drag-and-drop or file picker → `FormData` multipart `POST /ingest`
- **On panel open:** hydrates from `GET /ingest` (backend job list) so uploads that started before the panel was opened (or in a previous session) resume showing their progress
- `setInterval` at 2.5 s → `GET /ingest/{jobId}/status` → maps backend stage to UI stage and progress bar
- Active pollers tracked in `useRef<Map<jobId, intervalId>>`, cleared on panel unmount to avoid memory leaks

### Sidebar contract deletion

Trash icon appears on hover per contract row. On click:
- `window.confirm` with a destructive warning ("This cannot be undone")
- `DELETE /contracts/{id}` API call
- On success: removes from `contracts` and `selectedContracts` local state immediately

---

## 8. Storage Abstraction

`get_artifact_store()` returns one of two implementations:

| Mode | Implementation | Storage location |
|---|---|---|
| `USE_BLOB_ARTIFACTS=false` (dev) | `ArtifactStore` | Local `data/processed/<contractId>/` |
| `USE_BLOB_ARTIFACTS=true` (prod) | `BlobArtifactStore` | Azure Blob `artifacts/<contractId>/` |

Both expose the same interface:
`save_contract_artifacts()`, `save_summary()`, `load_summary()`, `get_tree()`, `get_index_docs()`, `get_chunks()`, `get_manifest()`

`SemanticRetriever` uses a module-level `_TREE_CACHE: Dict[str, Dict]` — `tree.json` is downloaded from Blob exactly once per contract per process lifetime. Subsequent queries for the same contract use the in-memory cache.

`GremlinWriter` wraps the Gremlin Python driver with:
- Tenacity retry logic for transient failures
- Explicit `reconnect()` on connection drops (WebSocket client is recreated, not just retried)
- `upsert_vertex` / `upsert_edge` helpers that use `.property()` chains so repeat calls are idempotent

---

## 9. Environment Configuration Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | ✅ | — | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_API_KEY` | ✅ | — | Azure OpenAI API key |
| `AZURE_OPENAI_API_VERSION` | — | `2024-10-21` | API version |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | — | `gpt-4-1-mini` | Chat model deployment name |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | — | `text-embedding-3-small` | Embedding model name |
| `AZURE_SEARCH_ENDPOINT` | ✅ | — | Azure AI Search endpoint |
| `AZURE_SEARCH_ADMIN_KEY` | ✅ | — | Azure AI Search admin key |
| `AZURE_SEARCH_INDEX` | — | `contract-knowledge-index` | Index name |
| `AZURE_BLOB_CONNECTION_STRING` | ✅ | — | Blob Storage connection string |
| `AZURE_BLOB_CONTAINER` | — | `contract360-artifacts` | Container name |
| `COSMOS_NOSQL_ENDPOINT` | ✅ | — | Cosmos DB NoSQL endpoint |
| `COSMOS_NOSQL_KEY` | ✅ | — | Cosmos DB NoSQL key |
| `COSMOS_NOSQL_DATABASE` | — | `contract360` | Database name |
| `GREMLIN_ENDPOINT` | — | — | Cosmos DB Gremlin endpoint (KG optional) |
| `GREMLIN_USERNAME` | — | — | `/dbs/<db>/colls/<graph>` |
| `GREMLIN_PASSWORD` | — | — | Gremlin primary key |
| `TENANT_ID` | — | `contract360-dev` | Gremlin partition key value |
| `ALLOWED_ORIGINS` | — | `localhost:5173,localhost:3000` | CORS allowed origins (comma-separated) |
| `USE_BLOB_ARTIFACTS` | — | `false` | Must be `true` in production |
| `USE_AZURE_OPENAI_EMBEDDINGS` | — | `false` | Must be `true` in production |
| `USE_AZURE_DOCUMENT_INTELLIGENCE` | — | `false` | High-quality PDF parsing |
| `USE_PAGEINDEX_API` | — | `false` | Hierarchical tree building |
