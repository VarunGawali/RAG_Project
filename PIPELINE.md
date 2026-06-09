# Contract360 — Pipeline Walkthrough

---

## 1. Document Ingestion Pipeline

**Entry point:** `POST /ingest` (multipart, returns HTTP 202 immediately)

### API layer (`app/api.py`)

- Reads uploaded bytes into memory, validates extension (`.pdf`, `.txt`, `.md`) and size (50 MB cap)
- Derives a `contractId` by sanitizing the filename (strips extension, replaces special characters)
- Creates a Cosmos DB job record (`ingest_jobs` container) with `status: queued`
- Uploads raw bytes to Azure Blob Storage at `uploads/<userId>/<jobId>/<filename>`
- Calls `worker.enqueue()` which submits `_run_job()` to a `ThreadPoolExecutor` and returns immediately
- Frontend receives job IDs back, starts polling `GET /ingest/{jobId}/status` every 2.5 seconds

### Background worker (`app/ingestion/worker.py`)

1. **Download** — fetches raw bytes from Blob, writes to a `tempfile.mkstemp()` ephemeral local path

2. **Parse** — `DocumentReader` extracts raw text (PDF via PyMuPDF or Azure Document Intelligence)

3. **Tree building** — one of two paths:
   - **PageIndex API** (`USE_PAGEINDEX_API=true`) — calls external REST API, polls until ready, uploads `tree.json` to Blob
   - **Fallback tree builder** — heuristic regex-based section/clause detection, builds a `TreeNode` dataclass tree
   - Both paths produce the same `TreeNode` structure (`nodeId`, `nodeType`, `title`, `text`, `parentNodeId`, `children[]`)

4. **Chunking** — `create_chunks()` flattens the tree, skips non-content node types (`document`/`article`), applies a sliding window of 850 words with 80-word overlap, infers `clauseType` from keyword matching (`termination`, `payment`, `liability`, etc.)

5. **Batch embedding** — `EmbeddingClient.embed_many()` sends batches of 16 texts per Azure OpenAI API call (`text-embedding-3-small`, 1536 dimensions). A 100-chunk contract makes 7 API calls instead of 100.

6. **Document summary** — one LLM call with the first 16k characters of raw text produces a structured JSON (`purpose`, `parties`, `effectiveDate`, `term`, `keyObligations`, `paymentSummary`, `terminationSummary`, `complianceTopics`), stored as `summary.json` in Blob

7. **Artifact persistence** — `BlobArtifactStore.save_contract_artifacts()` uploads `tree.json`, `chunks.json`, `index_docs.json`, `manifest.json` to `artifacts/<contractId>/` in Blob

8. **Azure AI Search upload** — batches index docs (500 per batch). Each doc carries: `contractId`, `nodeId`, `kgId` (graph bridge), `graphReady` (bool), `embedding` (float[1536]), `sectionTitle`, `clauseType`, `pageStart`, `pageEnd`, `sourcePath`

9. **KG pipeline** (runs as part of ingestion if Gremlin is configured):
   - `LegalLLMExtractor.extract_from_clause()` — LLM call per clause, extracts obligations, rights, restrictions, parties, deadlines, indemnity, termination, and breach facts as structured JSON
   - All clause extractions are collected as `extraction_dicts` (full coverage — no top-N cap, `limit=None`)
   - `resolve_one_contract()` runs the three-stage resolution pipeline:
     - **Normalization** — `OntologyNormalizer` maps raw LLM labels to the canonical 40-type ontology
     - **De-fragmentation** — `EntityResolver` merges duplicate mentions of the same entity (e.g. "Con Edison", "Con Edison Company of New York" → one node), deduplicates edges
     - **Canonicalization** — `Canonicalizer` links resolved nodes to cross-contract `CanonicalEntity` vertices (e.g. one canonical "Con Edison" shared across all contracts it appears in)
   - `write_resolved_graph()` writes the clean two-tier graph to Cosmos Gremlin:
     - **Tier 1** — mention-level nodes (`Obligation`, `Right`, `Restriction`, `Party`, etc.) with `clauseTitle`/`pageStart`/`pageEnd` denormalized directly onto each vertex (no structural clause vertex needed)
     - **Tier 2** — `CanonicalEntity` vertices linked via `RESOLVED_AS` edges, enabling cross-contract entity queries
   - Idempotent: deterministic vertex IDs mean re-ingesting a contract merges into existing graph rather than duplicating

10. **Job completion** — `JobStore.mark_done()` writes final status to Cosmos; frontend polling picks it up and adds the contract to the sidebar

---

## 2. Query Pipeline

**Entry point:** `POST /sessions/{session_id}/ask/stream` (SSE) or `POST /sessions/{session_id}/ask` (JSON)

### Step 0 — Chat history

- `SessionService.save_user_message()` persists the question to Cosmos
- `SessionService.build_llm_history()` fetches the last 12 messages (6 turns) to inject into the LLM prompt

### Step 0.5 — Summary shortcut

- `_is_summary_query()` checks against a set of exact phrase patterns ("summarize this contract", "what is this contract about?", etc.)
- If matched and a `summary.json` exists in Blob → `format_summary_as_answer()` returns the pre-generated summary immediately (zero retrieval, zero LLM call)

### Step 1 — Scope resolution (`contract_resolver.py`)

Before routing, the question is checked for explicit contract mentions:

- If `contract_ids` were passed by the UI (checkbox selection), those form the candidate pool
- If the question names a specific contract ("...in the Edison contract"), `resolve_scope()` narrows the scope to just that contract, regardless of what was selected in the UI
- This prevents cross-contract hallucination on portfolio-wide questions

### Step 2 — LLM-based query routing (`query_router.py`)

Single `AzureOpenAI.chat.completions.create()` call (`temperature=0`, `max_tokens=200`):

- **Input:** last 4 chat turns + current question + system prompt describing 3 routes
- **Output:** `route` (`tree` / `graph` / `hybrid`), `reasoning`, `rewritten_query` (pronouns resolved, context folded in), `structural_scope` (e.g. `{"type": "Article", "identifier": "XII"}` or `null`)
- **Comparison questions** (`compare`, `versus`, `differ`, `contrast`, etc.) always route to `hybrid`
- **Fallback:** if LLM call fails → `_keyword_route()` keyword classifier

### Step 3 — Retrieval (uses `rewritten_query`, not the original question)

#### `tree` route — `_tree_retrieve()`
- `AzureSearchTester.hybrid_search()`: embeds the rewritten query, sends a `VectorizedQuery` (k=30 nearest neighbours) combined with BM25 full-text search, OData-filtered by `contractId`
- If `structural_scope` is set, switches to `retrieve_structural_scope()` which filters by `sectionTitle` or `clauseTitle`
- Each hit is enriched by `SemanticRetriever.retrieve()`: loads `tree.json` from Blob (module-level `_TREE_CACHE` keyed by `contractId`, populated lazily), calls `expand_context(nodeId)` which fetches the node itself + parent + siblings + children

#### `graph` route — `_graph_retrieve()`
Two-phase approach:

**Phase 1 — Canonical entity-anchored (preferred):**
- `canonical_graph_retrieve()` links named entities in the question to `CanonicalEntity` vertices using span-aware longest-match (prevents "Edison" from matching SCE's alias)
- Traverses `RESOLVED_AS` edges to reach mention-level nodes, then follows `OWED_BY` / `OWED_TO` to obligations
- Returns structured fact blocks per entity with cross-contract reach

**Phase 2 — Vector-anchored fallback (when no entity linked):**
- Runs a vector search to find relevant clause IDs, then anchors to graph nodes via `sourceClauseId`
- Queries `Obligation`, `Right`, `Restriction`, `Event` nodes anchored on those clauses

**Semantic intent classification:**
- `_classify_intent()` embeds the question and computes cosine similarity against 13 pre-embedded intent descriptions (embedded once at startup, cached module-level)
- Picks the closest intent (`indemnity`, `termination`, `breach_cure`, `notice`, `payment`, `liability`, `deadline`, `rights`, `restrictions`, `all_obligations`, etc.)
- `_intent_to_fetcher()` maps intent → the right `GraphNativeRetriever` method — no keyword matching
- Falls back to `graph_native_retrieve()` if canonical phase returns nothing

#### `hybrid` route — `_hybrid_retrieve()`
- Runs `_tree_retrieve()` for clause text context, re-labels all citations as `route="hybrid"`
- Runs `_graph_retrieve()` for structured graph facts
- Merges both context blocks; produces citations from both sources

#### Comparison queries (2+ contracts, comparison intent)
- Detected by `_is_comparison()` before intent classification
- `_classify_intent()` identifies which topic is being compared (termination, payment, etc.)
- Fetches that topic's facts per contract, builds an explicit `CONTRACT A / CONTRACT B` side-by-side block with embedded instructions telling the LLM to compare, not summarise
- Shared parties across contracts appended as enrichment

### Step 4 — Answer grounding and generation

`_ground_and_generate()`:

1. Ranks citations by confidence score (descending)
2. Appends a numbered `SOURCES` list to the context (`[S1] Clause Title — Contract Name (pp. X-Y)`)
3. Calls `AnswerGenerator.generate()` — LLM call with `temperature=0`, `max_tokens=1200`; system prompt instructs the model to cite sources inline as `[S#]`
4. Extracts cited `[S#]` numbers from the answer with regex, returns only the cited citations (grounded subset), ordered by first appearance
5. Strips `[S#]` markers from the displayed answer
6. Falls back to top-8 ranked citations if the model cited nothing

For comparison questions the system prompt instructs a `**[Dimension]** / Contract A: ... / Contract B: ...` structure with an explicit Key Differences summary.

### Step 5 — SSE streaming (`/ask/stream`)

- `answer_question()` runs in a thread pool (`asyncio.get_event_loop().run_in_executor()`) so it doesn't block the async event loop
- As soon as the answer string is ready, the SSE generator yields word-by-word `{"type":"delta","content":"word "}` events via `asyncio.sleep(0)` yields between words (true async token delivery)
- Final event: `{"type":"done","message_id":"...","route":"...","reason":"...","citations":[...],"follow_up_suggestions":[...]}`
- Frontend `streamAsk()` in `client.ts` reads the `ReadableStream` line by line, parses each `data:` JSON event, calls `onDelta(token)` to append each word to the streaming message bubble, then `onDone(event)` to finalize with citations and follow-up chips

### Step 6 — Persist assistant message

- `SessionService.save_assistant_message()` appends to Cosmos with `route`, `citations`, and `follow_up_suggestions`
- Sets `previewText` (first 120 chars) and auto-titles the session from the first user question
- `follow_up_suggestions` are stored and restored in `GET /sessions/{id}/history` so they reappear when switching sessions

---

## 3. Cross-Contract Comparison Queries

When the user selects two contracts and asks a comparison question:

1. Scope resolver confirms both contracts are in scope
2. Router classifies as `hybrid` (comparison terms always trigger hybrid)
3. `_is_comparison()` fires before intent classification in `graph_native_retrieve()`
4. `_classify_intent()` identifies the topic (`termination`, `payment`, etc.)
5. Fetches that topic's graph facts filtered to the two contracts
6. `format_comparison_result()` builds a `CONTRACT A (id) / CONTRACT B (id)` side-by-side block with embedded LLM instructions
7. Tree search runs in parallel, providing clause text evidence for direct quotes
8. `_ground_and_generate()` produces a dimension-by-dimension comparison with Key Differences summary

---

## 4. Contract Delete Pipeline

**Entry point:** `DELETE /contracts/{contractId}`

Calls `delete_contract()` in `app/services/contract_delete.py`, which deletes best-effort across three stores:

1. **Azure AI Search** — `AzureSearchTester.delete_by_contract()` pages through all docs with `contractId eq '...'` and deletes in batches of 1000
2. **Cosmos Gremlin** — drops all vertices (and their edges) where `contractId` matches
3. **Azure Blob** — `BlobStore.delete_contract_artifacts()` deletes everything under `artifacts/<contractId>/`

Returns a per-store summary. Partial failures are reported, not raised — the UI shows which stores succeeded.

---

## 5. Chat Session Management

- Cosmos DB NoSQL container `chat_sessions`, partition key `/userId`
- `GET /sessions` uses a projection query (no `messages` array) for efficient sidebar loading
- History is lazy-loaded: `GET /sessions/{id}/history` fetches the full document only when a session is selected
- `follow_up_suggestions` stored per message, restored in history endpoint (defaults to `[]` for old messages)

---

## 6. Frontend Architecture

### State model (`App.tsx`)

- `sessions: ChatSession[]` — loaded from `GET /sessions` on mount
- `selectedContracts: string[]` — empty = portfolio-wide; non-empty = scoped retrieval via `contract_ids` in the ask payload
- `activeUploads: number` — polled every 4 seconds via `listIngestJobs()`, triggers `refreshContracts()` when a job finishes
- `refreshContracts` — `useCallback` that merges ingest jobs + Search index for the sidebar; called on mount and whenever active uploads drop

### Message flow (`handleSendMessage`)

1. Ensures active session exists (creates via `POST /sessions` if not)
2. Optimistically appends the user message and a streaming placeholder (`isStreaming: true, content: ""`) to local state
3. Calls `api.streamAsk()` which reads the SSE stream via `fetch` + `ReadableStream`
4. `onDelta(token)` appends each word to the streaming bubble in real time
5. `onDone(event)` replaces the placeholder with the final message including route badge, citation cards, and follow-up suggestion chips

### Upload flow (`UploadPanel.tsx`)

- Drag-and-drop or file picker → `FormData` multipart `POST /ingest`
- On panel open: hydrates from `GET /ingest` (backend job list) so in-progress uploads persist across panel close/reopen
- `setInterval` polling at 2.5 s calls `GET /ingest/{jobId}/status`, maps backend stage to UI stage (`uploading → parsing → embedding → indexing → extracting → graph_writing → done`)
- Active pollers tracked in a `useRef<Map>`, cleared on panel unmount

### Route badges

CSS classes `route-badge-{route}` applied dynamically: `tree` (amber), `graph` (emerald), `hybrid` (violet), `summary` (sky)

---

## 7. Storage Abstraction

`get_artifact_store()` factory returns either:

- `ArtifactStore` (`USE_BLOB_ARTIFACTS=false`) — reads/writes JSON files to local `data/processed/<contractId>/` (dev only)
- `BlobArtifactStore` (`USE_BLOB_ARTIFACTS=true`) — reads/writes to Azure Blob `artifacts/<contractId>/` via `BlobStore` (`BlobServiceClient.from_connection_string`)

Both expose the same interface: `save_contract_artifacts()`, `save_summary()`, `load_summary()`, `get_tree()`, `get_index_docs()`, `get_chunks()`, `get_manifest()`.

`SemanticRetriever` uses a module-level `_TREE_CACHE: Dict[str, Dict]` to avoid re-downloading `tree.json` from Blob on repeated queries within the same process lifetime.
