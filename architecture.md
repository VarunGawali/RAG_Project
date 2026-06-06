# Contract360 — Architecture

---

## System Layers

---

### 🖥️ Frontend (React + TypeScript + Vite)

| Component | Responsibilities |
|---|---|
| **ChatArea** | Message thread, suggested questions, streaming tokens |
| **Sidebar** | Session list, contract filter, delete session |
| **UploadPanel** | Drag & drop, multi-file, progress polling |

---

### ⚡ FastAPI (`app/api.py`)

| Endpoint Group | Routes |
|---|---|
| **Session endpoints** | `POST /sessions` · `GET /sessions` · `GET /sessions/{id}` · `GET /sessions/{id}/history` · `DEL /sessions/{id}` |
| **Ask endpoint** | `POST /sessions/{id}/ask` → save user msg → build LLM history slice → `answer_question()` → save assistant msg |
| **Ingest endpoints** | `POST /ingest` (multipart) · `GET /ingest/{id}/status` · `GET /ingest` — returns HTTP 202 async |
| **Health** | `GET /health` |

---

### 💬 Chat History (`app/chat_history/`)

| Component | Responsibilities |
|---|---|
| **SessionService** | create / get / list / delete session · `build_llm_history()` (last 6 turns) |
| **CosmosChatStore** | Container: `chat_sessions` · Partition: `/userId` · Doc: `{id, userId, title, contractFilter, messages:[...]}` |

---

### 🧠 Query Pipeline (`app/rag/`)

#### LLM Router (`query_router.py`)

- Azure OpenAI call — `temp=0`, `max_tokens=200`
- Includes last 4 chat turns for context
- **Output — `QueryPlan`:**
  - `route`: `search` | `graph` | `hybrid` | `tree`
  - `reasoning`: one sentence
  - `rewritten_query`: pronouns resolved
  - `structural_scope`: Article / Section / Clause
- Keyword classifier as fallback

#### Retrieval Routes (`query_service.py`)

| Route | Method |
|---|---|
| 🔍 **search** | Azure AI Search — hybrid keyword + vector, or structural scope (Article XII etc.) |
| 🕸️ **graph** | Cosmos Gremlin — direct semantic fact queries (obligations, rights, deadlines) |
| ⚡ **hybrid** | Azure AI Search → kgId bridge → Cosmos Gremlin neighbor expansion |
| 🌲 **tree** | SemanticRetriever → vector search + tree context expansion (parent / sibling / children nodes) |

#### AnswerGenerator (`answer_generator.py`)

- Azure OpenAI GPT-4 — `temp=0`, `max_tokens=1200`
- System prompt: contract analyst persona
- Messages: `[system]` + `[chat_history turns]` + `[user + context]`

---

### 🌲 TreeRAG (`app/tree/`)

| Component | Responsibilities |
|---|---|
| **SemanticRetriever** | Loads `tree.json` from Blob · Module-level cache `_TREE_CACHE` · Builds `node_lookup` + `children_lookup` · Vector search on Azure Search · `expand_context(nodeId)`: current + parent + siblings + children |
| **SemanticRAGChatAgent** | `retriever.retrieve()` → `build_rag_prompt()` → Azure OpenAI generate · supports `chat_history` |

---

### 📥 Ingestion Pipeline

#### API Layer (`app/api.py` + `app/ingestion/`)

| Component | Responsibilities |
|---|---|
| **JobStore** | Container: `ingest_jobs` · Partition: `/userId` · Status: `queued → processing → done \| failed` · Stage: `uploading → parsing → embedding → indexing → done` |
| **Worker** (ThreadPoolExecutor, max=4) | 1. Download raw file from Blob · 2. Write ephemeral temp file · 3. `IngestionService(BlobArtifactStore)` · 4. Upload `index_docs` → Azure Search · 5. `mark_done` in JobStore · ⚠️ Replace with Azure Service Bus for multi-instance |

#### IngestionService (`app/services/`)

| Component | Responsibilities |
|---|---|
| **DocumentReader** | Azure Document Intelligence or pypdf fallback |
| **TreeBuilder** | PageIndex API (`BlobPageIndexTreeGenerator`) or heading-based fallback parser |
| **Chunker** | Word-based · max 850 words · 80-word overlap · Clause type inference |
| **IndexBuilder** | `EmbeddingClient` → Azure OpenAI or local hash fallback |
| **`get_artifact_store()`** | `USE_BLOB_ARTIFACTS=true` → `BlobArtifactStore` (writes to Blob) · `USE_BLOB_ARTIFACTS=false` → `ArtifactStore` (writes to disk) |

---

### 🔬 Knowledge Graph Pipeline (offline scripts)

| Component | Responsibilities |
|---|---|
| **`normalize_tree.py`** | tree → KGNode vertices with kgId + edges |
| **`legal_extractor.py`** | Azure OpenAI extracts: Party, Obligation, Right, Restriction, Deadline… with confidence + evidence quotes |
| **GremlinWriter** | Writes vertices + edges to Cosmos Gremlin · Partition: `/pk` (tenantId) |

---

### ☁️ Azure Services

#### Azure Blob Storage

```
uploads/<userId>/<jobId>/<file>        ← raw files
artifacts/<contractId>/
  ├── raw_text.txt
  ├── tree.json                         ← TreeRAG source
  ├── chunks.json
  ├── index_docs.json
  ├── manifest.json
  ├── kg_normalized.json
  └── pageindex_tree.json
```

#### Azure AI Search

- **Index:** `contract-knowledge-index`
- **Fields:** `id`, `contractId`, `nodeId`, `title`, `sectionTitle`, `clauseTitle`, `clauseType`, `text`, `sourcePath`, `pageStart`, `pageEnd`, `embedding` (1536-dim HNSW), `kgId`, `parentKgId`, `graphReady`, `nodeType`, `graphLabel`
- **Search:** hybrid keyword + vector + semantic reranking

#### Cosmos DB — NoSQL API

```
DB: contract360
├── chat_sessions
│     partition: /userId
│     { id, userId, title, contractFilter,
│       messages: [{ role, content, timestamp, route, sources }] }
└── ingest_jobs
      partition: /userId
      { id, contractId, fileName, blobPath,
        status, stage, progress, result, error }
```

#### Cosmos DB — Gremlin API

- **Partition:** `/pk` (tenantId)
- **Vertex labels:** `Clause`, `Section`, `Article`, `Document`, `Party`, `Obligation`, `Right`, `Restriction`, `Deadline`…
- **Edge labels:** `HAS_PARENT`, `NEXT_SIBLING`, `OWED_BY`, `OWED_TO`, `HAS_DEADLINE`, `GRANTS_RIGHT`, `IMPOSES_OBLIGATION`, `EXTRACTED_ENTITY`…

#### Azure OpenAI

| Deployment | Used by | Tokens |
|---|---|---|
| `gpt-4-1-mini` (chat) | LLM Router | max 200 |
| `gpt-4-1-mini` (chat) | AnswerGenerator | max 1200 |
| `gpt-4-1-mini` (chat) | LegalExtractor (offline) | — |
| `text-embedding-3-small` | IndexBuilder (ingestion) | — |
| `text-embedding-3-small` | EmbeddingClient (retrieval) | — |

#### Azure Document Intelligence

- Layout model · Advanced PDF parsing
- Toggle: `USE_AZURE_DOCUMENT_INTELLIGENCE`

---

### 🌐 External Services

| Service | Role |
|---|---|
| **PageIndex API** | Document structure extraction · Poll-based · Optional (`USE_PAGEINDEX_API`) |

---

## Data Flow Narratives

### Query Flow (runtime)

```
User types question
  → POST /sessions/{id}/ask
  → SessionService.build_llm_history()   — last 6 turns from Cosmos NoSQL
  → route_question(question, chat_history)
      → Azure OpenAI (1 call, 200 tokens)
      → QueryPlan { route, rewritten_query, structural_scope }
      → keyword fallback if LLM fails
  → [search]  AzureSearchTester.hybrid_search(rewritten_query)
    [graph]   graph_native_retrieve → Cosmos Gremlin
    [hybrid]  hybrid_search → kgId → Gremlin neighbor expansion
    [tree]    SemanticRetriever → Blob tree.json (cached) → Search → expand_context()
  → AnswerGenerator.generate(question, context, chat_history)
      → Azure OpenAI (1 call, 1200 tokens)
      → [system] + [prior turns] + [context + question]
  → SessionService: save user msg + assistant msg to Cosmos NoSQL
  → Return { route, reason, rewritten_query, answer }
```

### Upload Flow (ingestion)

```
User drops files on UploadPanel
  → POST /ingest (multipart, up to 50 MB/file)
  → BlobStore.upload_raw_file()    — uploads/<userId>/<jobId>/<filename>
  → JobStore.create_job()          — ingest_jobs container, status=queued
  → worker.enqueue()               — ThreadPoolExecutor (max 4 concurrent)
  → HTTP 202 returned immediately with jobId(s)

Background worker per file:
  → Download raw bytes from Blob
  → Write ephemeral temp file
  → DocumentReader (Doc Intelligence or pypdf)
  → TreeBuilder   (BlobPageIndexTreeGenerator or heading fallback)
  → Chunker       (850-word clauses with 80-word overlap)
  → IndexBuilder  (EmbeddingClient → Azure OpenAI text-embedding-3-small)
  → BlobArtifactStore.save_contract_artifacts()  → Blob
  → AzureSearchIndexer.upload_documents()        → Azure AI Search
  → JobStore.mark_done()

Frontend polls GET /ingest/{jobId}/status every 2.5s
  → updates progress bar + stage dots
  → on done: calls onContractAdded() → contract appears in sidebar
```

### KG Build Flow (offline, one-time per contract)

```
python -m app.scripts.build_structural_kg
  → load tree from Blob (or local /data/processed/)
  → normalize_tree.py → KGNode vertices + structural edges
  → gremlin_writer.py → Cosmos Gremlin (structural graph)

python -m app.scripts.run_legal_extraction
  → legal_extractor.py → Azure OpenAI → Party, Obligation, Right…
  → gremlin_writer.py → Cosmos Gremlin (semantic graph)

After KG build, contract is "graph-enabled":
  → kgId fields populated in Azure Search → graphReady=true
  → hybrid + graph routes available for that contract
```

---

## Environment Variables Reference

| Variable | Used by | Required |
|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | Router, AnswerGenerator, IndexBuilder, LegalExtractor | ✅ |
| `AZURE_OPENAI_API_KEY` | Same | ✅ |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | Router, AnswerGenerator | ✅ |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | EmbeddingClient | ✅ |
| `AZURE_SEARCH_ENDPOINT` | AzureSearchTester, AzureSearchIndexer | ✅ |
| `AZURE_SEARCH_ADMIN_KEY` | Same | ✅ |
| `AZURE_SEARCH_INDEX` | Same | ✅ |
| `AZURE_BLOB_CONNECTION_STRING` | BlobStore | ✅ (cloud) |
| `AZURE_BLOB_CONTAINER` | BlobStore | ✅ (cloud) |
| `USE_BLOB_ARTIFACTS` | `get_artifact_store()` factory | `false` default |
| `COSMOS_NOSQL_ENDPOINT` | CosmosChatStore, JobStore | ✅ |
| `COSMOS_NOSQL_KEY` | Same | ✅ |
| `COSMOS_NOSQL_DATABASE` | Same | `contract360` default |
| `GREMLIN_ENDPOINT` | GremlinWriter, GraphContextRetriever | graph-only |
| `GREMLIN_DATABASE` / `GREMLIN_GRAPH` | Same | graph-only |
| `GREMLIN_PASSWORD` | Same | graph-only |
| `TENANT_ID` | Gremlin partition key | `contract360-dev` default |
| `USE_AZURE_DOCUMENT_INTELLIGENCE` | DocumentReader | `false` default |
| `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT/KEY` | Same | if above = `true` |
| `USE_PAGEINDEX_API` | IngestionService | `false` default |
| `PAGEINDEX_API_KEY` | PageIndexTreeGenerator | if above = `true` |