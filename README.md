# Contract360 — Contract Intelligence Platform

A production-style RAG platform for querying energy/utility contracts in natural language.
It combines **hierarchical document retrieval** (clause text, structure, summaries) with a
**two-tier canonical knowledge graph** (cross-document entities & relationships), and routes
each question to the right strategy automatically.

---

## What it does

- **Ask questions across a portfolio of contracts** and get grounded, cited answers.
- **Two retrieval brains, auto-selected per question:**
  - **Tree** — clause text, summaries, "what does Section 5.2 say?", structural navigation.
  - **Graph** — obligations, rights, deadlines, parties, and **cross-contract** relationships.
  - **Hybrid** — both, merged, when a question needs clause evidence *and* structured facts.
- **Canonical entity resolution** — "Con Edison", "Consolidated Edison Company of New York, Inc.",
  and "the utility" all resolve to **one** entity, so "Con Edison's obligations" returns the
  *complete* set, not a fragment.
- **Answer-grounded citations** — the model cites its sources inline; the UI shows exactly the
  clauses (with page ranges) that back the answer, ranked by extraction confidence.
- **Async ingestion** — upload a PDF → parse → tree → chunk → embed → index → extract KG →
  resolve → write canonical graph. Progress is tracked and survives UI refreshes.
- **Full lifecycle** — upload, query, and **delete** a contract (removes it from search, the
  graph, and blob storage in one action).

---

## Architecture

```
                         ┌─────────────────────────────────────────────┐
   React (Vite) UI  ───▶ │  FastAPI  (app/api.py)                       │
   sessions / chat       │   /sessions  /ask  /ask/stream  /ingest      │
   contracts / upload    │   /contracts (GET, DELETE)                   │
                         └───────────────┬─────────────────────────────┘
                                         │
                 ┌───────────────────────┼───────────────────────────────┐
                 ▼                       ▼                               ▼
        Query understanding      Ingestion worker               Storage
        (app/rag/query_router)   (app/ingestion/worker)         • Azure AI Search (chunks+vectors)
                 │                parse→tree→chunk→embed→        • Cosmos Gremlin (semantic graph)
     ┌───────────┴──────────┐    index→extract→RESOLVE→write    • Azure Blob (raw + artifacts)
     ▼                      ▼                                    • Cosmos (sessions + jobs)
  TREE route            GRAPH route
  semantic_retriever    graph_canonical (canonical-anchored)
  + Azure Search        + Azure Search vector bridge (fallback)
     │                      │
     └──────────┬───────────┘
                ▼
   Answer generation (app/rag/answer_generator) — grounded [S#] citations
```

### The two-tier knowledge graph (the core idea)

The semantic graph is rebuilt deterministically from saved LLM extractions into a clean,
connected structure:

- **Tier 1 — mention nodes** (per contract, clause-anchored): `Obligation`, `Party`,
  `TemporalConstraint`, `Event`, … with denormalized citation metadata (clause title, page).
- **Tier 2 — canonical entities** (global): one `CanonicalEntity` per real-world org/regulator,
  joined to its mentions by `RESOLVED_AS` edges.

Cross-contract questions become a **one-hop traversal**:

```groovy
g.V('canonical:org:con_edison').in('RESOLVED_AS').in('OWED_BY').count()   // all Con Edison obligations
g.V('canonical:regulator:nerc').in('RESOLVED_AS').values('contractId')   // contracts referencing NERC
```

A **role-vs-named guard** keeps things correct: real entities merge across their name variants,
but role placeholders ("Buyer", "Seller", "Party") are never merged, and distinct orgs stay
apart (Con Edison ≠ Southern California Edison).

Design details: [docs/kg_redesign_spec.md](docs/kg_redesign_spec.md).

---

## Tech stack

| Layer | Tech |
|---|---|
| Frontend | React + Vite + TypeScript + Tailwind |
| API | FastAPI (Python) |
| LLM | Azure OpenAI (`gpt-4.1-mini`) |
| Vector + keyword search | Azure AI Search (hybrid BM25 + vector) |
| Knowledge graph | Azure Cosmos DB (Gremlin) |
| Storage | Azure Blob (raw files + artifacts) |
| Sessions / jobs | Azure Cosmos DB (SQL API) |

---

## Setup

### 1. Backend

```bash
python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then fill in your Azure credentials
```

Key env vars (see `.env.example` for the full list):

```
AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY / AZURE_OPENAI_API_VERSION
AZURE_OPENAI_CHAT_DEPLOYMENT          # e.g. gpt-4.1-mini
AZURE_SEARCH_ENDPOINT / AZURE_SEARCH_INDEX / AZURE_SEARCH_ADMIN_KEY
GREMLIN_ENDPOINT / GREMLIN_USERNAME / GREMLIN_PASSWORD
AZURE_BLOB_CONNECTION_STRING / AZURE_BLOB_CONTAINER
TENANT_ID
ALLOWED_ORIGINS                       # e.g. http://localhost:5173
```

> **Important:** the API process must have the `GREMLIN_*` vars set, or graph routing is
> disabled and everything falls back to tree search.

Run it:

```bash
uvicorn app.api:app --reload --port 8000
# Swagger UI: http://localhost:8000/docs
```

### 2. Frontend

```bash
cd frontend
npm install
echo "VITE_API_BASE_URL=http://localhost:8000" > .env   # no trailing slash
npm run dev        # http://localhost:5173
```

---

## Building the knowledge graph

Contracts uploaded through the UI are resolved and written automatically by the worker.
To (re)build the whole semantic graph from saved extractions:

```bash
# 1. Audit the resolution offline (writes nothing) — see what the clean graph will look like
python -m app.scripts.audit_kg_resolution

# 2. Try the writer on one contract (no clearing)
python -m app.scripts.rebuild_semantic_kg --contract SoCal_EPC --write --no-clear --delay 0.1

# 3. Full rebuild: clear the old graph, write the clean two-tier graph (RU-safe)
python -m app.scripts.rebuild_semantic_kg --write --clear --yes --delay 0.1 --clear-batch 25
```

Inspect / verify:

```bash
python -m app.scripts.inspect_kg_health      # fragmentation, cross-contract, connectivity
python -m app.scripts.check_semantic_kg       # entity/edge counts
python -m app.scripts.query_resolved_kg       # offline query tester over data/kg/resolved
```

---

## Key API endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/sessions` | Create a chat session |
| `POST` | `/sessions/{id}/ask` | Ask (returns answer + citations) |
| `POST` | `/sessions/{id}/ask/stream` | Streaming answer (SSE) |
| `GET`  | `/sessions/{id}/history` | Message history |
| `POST` | `/ingest` | Upload contract(s) → returns job ids |
| `GET`  | `/ingest` / `/ingest/{job}/status` | Track ingestion |
| `GET`  | `/contracts` | List indexed contracts |
| `DELETE` | `/contracts/{id}` | Delete from search + graph + blob |

---

## Project structure

```
app/
  api.py                  FastAPI app + endpoints
  rag/
    query_router.py       intent routing (tree | graph | hybrid)
    query_service.py      orchestration: route → retrieve → ground → answer
    contract_resolver.py  two-stage scoping (UI selection + question text)
    graph_canonical.py    canonical-anchored graph retrieval (+ vector bridge)
    graph_retriever.py    legacy template graph retrieval (fallback)
    answer_generator.py   grounded answer + [S#] citations + follow-ups
  kg/
    legal_extractor.py    LLM extraction (ontology)
    resolution/           normalize → de-fragment → canonicalize → write
  ingestion/worker.py     async ingest pipeline (parse→…→resolve→write)
  indexing/search_tester.py  Azure AI Search (hybrid search, list, delete)
  storage/                blob + artifact stores
  services/contract_delete.py  multi-store delete
  scripts/                rebuild, audit, inspect, query tools
frontend/                 React UI
docs/kg_redesign_spec.md  knowledge-graph design spec
```

---

## Demo sequence (≈10 min)

A presenter-ready flow that shows each capability. Have 6–8 contracts ingested
(e.g. Edison/NYPA, SoCal EPC, Duke PPA, Terra-Gen PPA, NextEra, SunPower).

**0. Setup (before the room)** — API + frontend running, sidebar showing the contract list.

**1. The problem (30s).** "Contracts hide obligations across dozens of clauses and many
documents. Keyword search misses context; reading them is slow." Open the app.

**2. Tree retrieval — clause Q&A (1.5 min).**
- Select the **Edison** contract in the sidebar.
- Ask: **"What does this contract say about force majeure?"**
- Point out: a clean answer **with source cards** (section + page range). Expand a card to show
  the exact clause text. → *"It's grounded in the document, not hallucinated."*

**3. Graph retrieval — entity resolution (2 min). The headline.**
- Clear the contract selection ("All contracts").
- Ask: **"What are Con Edison's obligations?"**
- Point out:
  - A complete, **numbered** list of obligations.
  - **Source cards** ranked by confidence, showing the clauses that back each claim.
  - *"Behind the scenes, 'Con Edison' appears under 5 different names across the contract.
    The graph merged them into one entity — so you get the full picture, not a fragment."*

**4. Cross-contract relationships (1.5 min).**
- Ask: **"Which contracts reference NERC?"** → answers across multiple contracts.
- Ask: **"Which regulators appear in more than one contract?"** → NERC, NYISO, …
- *"This is the cross-document layer — shared regulators and parties linked across the portfolio."*

**5. Disambiguation — the 'Edison' trap (45s).**
- Ask: **"Summarize the indemnification in the Edison contract."**
- Point out it answers from **Southern California Edison (SoCal)** — *not* Con Edison.
- *"The system knows 'Edison' here means a different company. It never conflates them."*

**6. Hybrid — facts + evidence (1 min).**
- Ask: **"What are Con Edison's environmental obligations, with citations?"**
- Point out: structured obligations **plus** the supporting clause text, cited together.

**7. Scoping intelligence (45s).**
- With nothing selected, ask: **"What obligations survive termination in the Terra-Gen contract?"**
- Point out it auto-scoped to Terra-Gen from the question text — no manual filter needed.

**8. Upload & lifecycle (1.5 min).**
- Click **Upload Contract**, drop a PDF. Show the live progress (parsing → embedding → graph).
- **Close the drawer** — point out the sidebar still shows **"Processing 1 upload…"**.
- When done, the contract appears in the sidebar automatically.
- Hover a contract → **trash icon** → delete. *"One click removes it from search, the graph,
  and storage — full lifecycle."*

**9. Under the hood (1 min, optional/technical audience).**
- Show Swagger `/docs`, or run in a terminal:
  ```groovy
  g.V('canonical:org:con_edison').in('RESOLVED_AS').in('OWED_BY').count()
  ```
  → returns the full obligation count. *"That one-hop traversal is what powers the smart answers."*
- Mention: deterministic rebuild from saved extractions, role-vs-named guard, bounded retrieval
  (scalable, no context blowups), answer-grounded citations.

**Close (30s).** "Tree for text, graph for relationships, auto-routed — with entity resolution
that makes cross-contract questions actually work, and citations you can trust."

### Quick-fire backup questions
- "What does the Power Authority owe?"
- "What are the termination provisions?"
- "Compare payment obligations across the contracts."
- "What is the SoCal EPC contract about?" (summary shortcut)
```