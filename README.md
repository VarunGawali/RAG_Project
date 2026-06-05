# Contract Ingestion + Indexing POC - Person 1

This is the **Person 1 data layer** for the contract assistant POC.

It does:

- read PDFs / TXT / MD
- optionally use PageIndex tree JSON
- fallback-build a contract tree from headings
- create clause-aware chunks
- create local embeddings
- create retrieval-ready `index_docs.json`
- create one combined `corpus_index_docs.json` for your friend's retrieval layer
- optionally upload docs to Azure AI Search later

No graph. No Cosmos required for POC.

---

## Quick Start

```bash
cd contract_ingestion_indexing_poc
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate
pip install -r requirements.txt
```

### Ingest one sample contract

```bash
python -m app.cli ingest-file --file examples/sample_contract.txt --contract-id demo
```

### Ingest a folder of PDFs/TXT files

Put your 9 PDFs here:

```text
samples/raw_contracts/
```

Then run:

```bash
python -m app.cli ingest-folder --folder samples/raw_contracts
```

### If PageIndex JSON exists

Expected convention:

```text
samples/pageindex_trees/{contract_id}.json
```

Then run:

```bash
python -m app.cli ingest-folder \
  --folder samples/raw_contracts \
  --pageindex-folder samples/pageindex_trees
```

### Validate outputs

```bash
python -m app.cli validate --processed-dir data/processed
```

---

## Output Structure

```text
data/processed/
  corpus_manifest.json
  corpus_index_docs.json

  {contract_id}/
    raw_text.txt
    tree.json
    chunks.json
    index_docs.json
    manifest.json
```

Your friend's retrieval side should read:

```text
data/processed/corpus_index_docs.json
```

or per contract:

```text
data/processed/{contract_id}/index_docs.json
```

---

## Core Data Contracts

Each `index_doc` contains:

```json
{
  "id": "chunk_demo_...",
  "contractId": "demo",
  "documentId": "demo_doc",
  "itemType": "clause_chunk",
  "nodeId": "clause_demo_...",
  "parentNodeId": "section_demo_...",
  "title": "4.2 Termination for Convenience",
  "sectionTitle": "4. Termination",
  "clauseTitle": "4.2 Termination for Convenience",
  "clauseType": "termination",
  "text": "Customer may terminate...",
  "pageStart": 4,
  "pageEnd": 4,
  "sourcePath": "demo > 4. Termination > 4.2 Termination for Convenience",
  "embedding": [...],
  "metadata": {}
}
```

---

## Production Replacement Later

- `local_embeddings.py` → Azure OpenAI embeddings
- `pdf_reader.py` → Azure Document Intelligence prebuilt-layout
- `corpus_index_docs.json` → Azure AI Search index
- `tree.json` → Blob/Cosmos storage
