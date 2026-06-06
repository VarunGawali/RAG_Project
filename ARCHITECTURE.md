# Contract360 — Architecture Diagram

```mermaid
%%{init: {"theme": "dark", "flowchart": {"rankSpacing": 60, "nodeSpacing": 40}}}%%
flowchart TB

  %% ─────────────────────────────────────────
  %% LAYER: USER / FRONTEND
  %% ─────────────────────────────────────────

  subgraph FE["🖥️  Frontend  (React + TypeScript + Vite)"]
    direction LR
    UI_CHAT["ChatArea\n─────────────\nMessage thread\nSuggested Qs\nStreaming tokens"]
    UI_SIDEBAR["Sidebar\n─────────────\nSession list\nContract filter\nDelete session"]
    UI_UPLOAD["UploadPanel\n─────────────\nDrag & drop\nMulti-file\nProgress polling"]
  end

  %% ─────────────────────────────────────────
  %% LAYER: API
  %% ─────────────────────────────────────────

  subgraph API["⚡  FastAPI  (app/api.py)"]
    direction TB
    EP_SESSION["Session endpoints\n───────────────────\nPOST /sessions\nGET  /sessions\nGET  /sessions/{id}\nGET  /sessions/{id}/history\nDEL  /sessions/{id}"]
    EP_ASK["Ask endpoint\n───────────────────\nPOST /sessions/{id}/ask\n\n1. save user message\n2. build LLM history slice\n3. answer_question()\n4. save assistant message"]
    EP_INGEST["Ingest endpoints\n───────────────────\nPOST /ingest  (multipart)\nGET  /ingest/{id}/status\nGET  /ingest\n\nHTTP 202 — async"]
    EP_HEALTH["GET /health"]
  end

  %% ─────────────────────────────────────────
  %% LAYER: CHAT HISTORY
  %% ─────────────────────────────────────────

  subgraph HIST["💬  Chat History  (app/chat_history/)"]
    direction LR
    SVC_SESSION["SessionService\n─────────────\ncreate / get / list\ndelete session\nbuild_llm_history()\n(last 6 turns)"]
    STORE_COSMOS["CosmosChatStore\n─────────────\nContainer: chat_sessions\nPartition: /userId\nDoc: {id, userId, title,\n  contractFilter,\n  messages:[...]}"]
  end

  %% ─────────────────────────────────────────
  %% LAYER: QUERY PIPELINE
  %% ─────────────────────────────────────────

  subgraph QPIPE["🧠  Query Pipeline  (app/rag/)"]
    direction TB

    ROUTER["LLM Router  (query_router.py)\n────────────────────────────────\nAzure OpenAI call  temp=0  max_tokens=200\nIncludes last 4 chat turns for context\n\nQueryPlan output:\n  route: search | graph | hybrid | tree\n  reasoning: one sentence\n  rewritten_query: pronouns resolved\n  structural_scope: Article/Section/Clause\n\nKeyword classifier as fallback"]

    subgraph ROUTES["Retrieval Routes  (query_service.py)"]
      direction LR
      R_SEARCH["🔍 search\n──────────\nAzure AI Search\nhybrid keyword+vector\nor structural scope\n(Article XII etc.)"]
      R_GRAPH["🕸️ graph\n──────────\nCosmos Gremlin\ndirect semantic\nfact queries\n(obligations,\nrights,\ndeadlines)"]
      R_HYBRID["⚡ hybrid\n──────────\nAzure AI Search\n→ kgId bridge\n→ Cosmos Gremlin\nneighbor expansion"]
      R_TREE["🌲 tree\n──────────\nSemanticRetriever\nvector search +\ntree context\nexpansion\n(parent/sibling/\nchildren nodes)"]
    end

    ANSWER_GEN["AnswerGenerator  (answer_generator.py)\n────────────────────────────────────────\nAzure OpenAI  GPT-4  temp=0  max_tokens=1200\nSystem prompt: contract analyst persona\nMessages array:\n  [system] + [chat_history turns] + [user+context]"]
  end

  %% ─────────────────────────────────────────
  %% LAYER: TREE RAG
  %% ─────────────────────────────────────────

  subgraph TREERAG["🌲  TreeRAG  (app/tree/)"]
    direction TB
    SEM_RET["SemanticRetriever\n─────────────────────\nLoads tree.json from Blob\nModule-level cache _TREE_CACHE\nBuilds node_lookup +\n  children_lookup\nVector search on Azure Search\nexpand_context(nodeId):\n  current + parent +\n  siblings + children"]
    TREE_AGENT["SemanticRAGChatAgent\n─────────────────────\nretriever.retrieve()\nbuild_rag_prompt()\nAzure OpenAI generate\nsupports chat_history"]
  end

  %% ─────────────────────────────────────────
  %% LAYER: INGESTION PIPELINE
  %% ─────────────────────────────────────────

  subgraph INGEST["📥  Ingestion Pipeline"]
    direction TB

    subgraph INGEST_API["API Layer  (app/api.py + app/ingestion/)"]
      direction LR
      JOB_STORE["JobStore\n──────────────\nContainer: ingest_jobs\nPartition: /userId\nstatus: queued →\n  processing →\n  done | failed\nstage: uploading →\n  parsing →\n  embedding →\n  indexing → done"]
      WORKER["Worker  (ThreadPoolExecutor  max=4)\n─────────────────────────────\n1. download raw file from Blob\n2. write ephemeral temp file\n3. IngestionService(BlobArtifactStore)\n4. upload index_docs → Azure Search\n5. mark_done in JobStore\n\nNOTE: replace with Azure\nService Bus for multi-instance"]
    end

    subgraph INGEST_SVC["IngestionService  (app/services/)"]
      direction LR
      DOC_READER["DocumentReader\n──────────────\nAzure Document\nIntelligence\nor pypdf fallback"]
      TREE_BUILDER["TreeBuilder\n──────────────\nPageIndex API\n(BlobPageIndex\nTreeGenerator)\nor heading-based\nfallback parser"]
      CHUNKER["Chunker\n──────────────\nWord-based\nmax 850 words\n80-word overlap\nClause type\ninference"]
      IDX_BUILDER["IndexBuilder\n──────────────\nEmbeddingClient\n→ Azure OpenAI\nor local hash\nfallback"]
      ARTIFACT_STORE["get_artifact_store()\n──────────────────\nUSE_BLOB_ARTIFACTS=true\n→ BlobArtifactStore\n  (writes to Blob)\n\nUSE_BLOB_ARTIFACTS=false\n→ ArtifactStore\n  (writes to disk)"]
    end
  end

  %% ─────────────────────────────────────────
  %% LAYER: KG PIPELINE (offline / scripts)
  %% ─────────────────────────────────────────

  subgraph KG["🔬  Knowledge Graph Pipeline  (offline scripts)"]
    direction LR
    KG_NORM["normalize_tree.py\n───────────────\ntree → KGNode\nvertices with\nkgId + edges"]
    KG_EXTRACT["legal_extractor.py\n───────────────\nAzure OpenAI\nextracts: Party,\nObligation, Right,\nRestriction,\nDeadline…\nwith confidence\n+ evidence quotes"]
    GREMLIN_W["GremlinWriter\n───────────────\nWrites vertices\n+ edges to\nCosmos Gremlin\nPartition: /pk\n(tenantId)"]
  end

  %% ─────────────────────────────────────────
  %% AZURE SERVICES
  %% ─────────────────────────────────────────

  subgraph AZURE["☁️  Azure Services"]
    direction TB

    BLOB["Azure Blob Storage\n─────────────────────────────\nuploads/<userId>/<jobId>/<file>  ← raw files\nartifacts/<contractId>/\n  ├── raw_text.txt\n  ├── tree.json          ← TreeRAG source\n  ├── chunks.json\n  ├── index_docs.json\n  ├── manifest.json\n  ├── kg_normalized.json\n  └── pageindex_tree.json"]

    SEARCH["Azure AI Search\n─────────────────────────────\nIndex: contract-knowledge-index\nFields: id, contractId, nodeId,\n  title, sectionTitle, clauseTitle,\n  clauseType, text, sourcePath,\n  pageStart, pageEnd,\n  embedding (1536-dim HNSW),\n  kgId, parentKgId, graphReady,\n  nodeType, graphLabel\nSearch: hybrid keyword + vector\n        + semantic reranking"]

    COSMOS_NOSQL["Cosmos DB  (NoSQL API)\n─────────────────────────────\nDB: contract360\n├── chat_sessions\n│     partition: /userId\n│     {id, userId, title,\n│      contractFilter,\n│      messages:[{role,content,\n│        timestamp,route,sources}]}\n└── ingest_jobs\n      partition: /userId\n      {id, contractId, fileName,\n       blobPath, status, stage,\n       progress, result, error}"]

    COSMOS_GREMLIN["Cosmos DB  (Gremlin API)\n─────────────────────────────\nPartition: /pk (tenantId)\nVertex labels:\n  Clause, Section, Article,\n  Document, Party, Obligation,\n  Right, Restriction, Deadline…\nEdge labels:\n  HAS_PARENT, NEXT_SIBLING,\n  OWED_BY, OWED_TO,\n  HAS_DEADLINE, GRANTS_RIGHT,\n  IMPOSES_OBLIGATION,\n  EXTRACTED_ENTITY…"]

    OPENAI["Azure OpenAI\n─────────────────────────────\nChat: gpt-4-1-mini\n  → LLM Router    (max 200 tok)\n  → AnswerGenerator (max 1200 tok)\n  → LegalExtractor (offline)\n\nEmbeddings: text-embedding-3-small\n  → IndexBuilder (ingestion)\n  → EmbeddingClient (retrieval)"]

    DOC_INTEL["Azure Document Intelligence\n─────────────────────────────\nLayout model\nAdvanced PDF parsing\n(optional, toggle:\nUSE_AZURE_DOCUMENT_INTELLIGENCE)"]
  end

  %% ─────────────────────────────────────────
  %% EXTERNAL
  %% ─────────────────────────────────────────

  PAGEINDEX_EXT["PageIndex API\n(external)\n──────────\nDocument structure\nextraction service\nPoll-based\nOptional toggle"]

  %% ─────────────────────────────────────────
  %% CONNECTIONS: Frontend ↔ API
  %% ─────────────────────────────────────────

  UI_CHAT      -- "POST /sessions/{id}/ask\nGET  /sessions\nX-User-Id header" --> EP_ASK
  UI_SIDEBAR   -- "GET/DEL /sessions" --> EP_SESSION
  UI_UPLOAD    -- "POST /ingest  multipart\nGET  /ingest/{id}/status  poll 2.5s" --> EP_INGEST

  %% ─────────────────────────────────────────
  %% CONNECTIONS: API ↔ Services
  %% ─────────────────────────────────────────

  EP_SESSION   <--> SVC_SESSION
  EP_ASK       --> SVC_SESSION
  EP_ASK       --> ROUTER
  EP_INGEST    --> BLOB
  EP_INGEST    --> JOB_STORE
  EP_INGEST    --> WORKER

  %% ─────────────────────────────────────────
  %% CONNECTIONS: Chat history
  %% ─────────────────────────────────────────

  SVC_SESSION  <--> STORE_COSMOS
  STORE_COSMOS <--> COSMOS_NOSQL

  %% ─────────────────────────────────────────
  %% CONNECTIONS: Query pipeline
  %% ─────────────────────────────────────────

  ROUTER       --> ROUTES
  ROUTER       <-- "chat_history\n(last 4 turns)" --- EP_ASK

  R_SEARCH     --> SEARCH
  R_GRAPH      --> COSMOS_GREMLIN
  R_HYBRID     --> SEARCH
  R_HYBRID     --> COSMOS_GREMLIN
  R_TREE       --> SEM_RET

  SEM_RET      --> BLOB
  SEM_RET      --> SEARCH

  ROUTES       --> ANSWER_GEN
  ANSWER_GEN   --> OPENAI

  %% ─────────────────────────────────────────
  %% CONNECTIONS: Ingestion
  %% ─────────────────────────────────────────

  WORKER       --> BLOB
  WORKER       --> DOC_READER
  WORKER       --> TREE_BUILDER
  WORKER       --> CHUNKER
  WORKER       --> IDX_BUILDER
  WORKER       --> ARTIFACT_STORE
  WORKER       --> SEARCH
  WORKER       --> JOB_STORE

  DOC_READER   --> DOC_INTEL
  TREE_BUILDER --> PAGEINDEX_EXT
  TREE_BUILDER --> BLOB
  IDX_BUILDER  --> OPENAI
  ARTIFACT_STORE --> BLOB

  %% ─────────────────────────────────────────
  %% CONNECTIONS: KG Pipeline (offline)
  %% ─────────────────────────────────────────

  KG_NORM      --> BLOB
  KG_EXTRACT   --> OPENAI
  KG_EXTRACT   --> GREMLIN_W
  GREMLIN_W    --> COSMOS_GREMLIN
  KG_NORM      --> GREMLIN_W

  %% ─────────────────────────────────────────
  %% STYLING
  %% ─────────────────────────────────────────

  classDef azure    fill:#0078d4,stroke:#005a9e,color:#fff
  classDef frontend fill:#20232a,stroke:#61dafb,color:#61dafb
  classDef api      fill:#1a1a2e,stroke:#e94560,color:#fff
  classDef service  fill:#16213e,stroke:#0f3460,color:#fff
  classDef external fill:#2d2d2d,stroke:#888,color:#ccc

  class BLOB,SEARCH,COSMOS_NOSQL,COSMOS_GREMLIN,OPENAI,DOC_INTEL azure
  class UI_CHAT,UI_SIDEBAR,UI_UPLOAD frontend
  class EP_SESSION,EP_ASK,EP_INGEST,EP_HEALTH api
  class PAGEINDEX_EXT external
```

---

## Data Flow Narratives

### Query Flow (runtime)
```
User types question
  → POST /sessions/{id}/ask
  → SessionService.build_llm_history()  — last 6 turns from Cosmos NoSQL
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
  → BlobStore.upload_raw_file()   — uploads/<userId>/<jobId>/<filename>
  → JobStore.create_job()         — ingest_jobs container, status=queued
  → worker.enqueue()              — ThreadPoolExecutor (max 4 concurrent)
  → HTTP 202 returned immediately with jobId(s)

Background worker per file:
  → Download raw bytes from Blob
  → Write ephemeral temp file
  → DocumentReader (Doc Intelligence or pypdf)
  → TreeBuilder   (BlobPageIndexTreeGenerator or heading fallback)
  → Chunker       (850-word clauses with 80-word overlap)
  → IndexBuilder  (EmbeddingClient → Azure OpenAI text-embedding-3-small)
  → BlobArtifactStore.save_contract_artifacts() → Blob
  → AzureSearchIndexer.upload_documents()       → Azure AI Search
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
| `USE_BLOB_ARTIFACTS` | get_artifact_store() factory | `false` default |
| `COSMOS_NOSQL_ENDPOINT` | CosmosChatStore, JobStore | ✅ |
| `COSMOS_NOSQL_KEY` | Same | ✅ |
| `COSMOS_NOSQL_DATABASE` | Same | `contract360` default |
| `GREMLIN_ENDPOINT` | GremlinWriter, GraphContextRetriever | graph-only |
| `GREMLIN_DATABASE` / `GREMLIN_GRAPH` | Same | graph-only |
| `GREMLIN_PASSWORD` | Same | graph-only |
| `TENANT_ID` | Gremlin partition key | `contract360-dev` default |
| `USE_AZURE_DOCUMENT_INTELLIGENCE` | DocumentReader | `false` default |
| `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT/KEY` | Same | if above = true |
| `USE_PAGEINDEX_API` | IngestionService | `false` default |
| `PAGEINDEX_API_KEY` | PageIndexTreeGenerator | if above = true |
