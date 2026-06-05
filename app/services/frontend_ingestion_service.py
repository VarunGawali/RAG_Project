"""
Frontend ingestion service.

Used by Streamlit.

Flow:
uploaded file
→ save to data/uploads/{contract_id}/
→ run existing IngestionService
→ upload generated index_docs.json to Azure AI Search

Graph upsertion is intentionally skipped for demo.
"""

import json
import re
from pathlib import Path
from typing import Dict, Optional

from app import config
from app.services.ingestion_service import IngestionService
from app.indexing.azure_search_uploader import AzureSearchIndexer


UPLOAD_DIR = Path("data/uploads")


def sanitize_contract_id(value: str) -> str:
    """
    Create a safe contract ID from uploaded filename or user input.
    """
    value = (value or "").strip()

    if not value:
        value = "uploaded_contract"

    value = re.sub(r"[^A-Za-z0-9_\-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")

    return value or "uploaded_contract"


def save_uploaded_file(uploaded_file, contract_id: str) -> Path:
    """
    Save Streamlit uploaded file to data/uploads/{contract_id}/.
    """
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    contract_upload_dir = UPLOAD_DIR / contract_id
    contract_upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = contract_upload_dir / uploaded_file.name

    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    return file_path


def get_index_docs_path(contract_id: str) -> Path:
    """
    Expected output path produced by IngestionService.
    """
    return config.PROCESSED_DIR / contract_id / "index_docs.json"


def ingest_and_upload_to_search(
    uploaded_file,
    contract_id: Optional[str] = None,
    pageindex_json: Optional[str] = None,
    ensure_index: bool = False,
    batch_size: int = 500,
) -> Dict:
    """
    Process uploaded file and upload generated index docs to Azure AI Search.

    This does NOT write to Cosmos Gremlin.

    For demo:
    - uploaded contracts become search-only contracts
    - graphReady will be false because kg_path=None
    """

    inferred_contract_id = sanitize_contract_id(
        contract_id or Path(uploaded_file.name).stem
    )

    saved_file_path = save_uploaded_file(
        uploaded_file=uploaded_file,
        contract_id=inferred_contract_id,
    )

    ingestion_service = IngestionService()

    ingestion_result = ingestion_service.ingest_file(
        file_path=str(saved_file_path),
        contract_id=inferred_contract_id,
        pageindex_json=pageindex_json,
    )

    index_docs_path = get_index_docs_path(inferred_contract_id)

    if not index_docs_path.exists():
        raise FileNotFoundError(
            f"index_docs.json not found after ingestion: {index_docs_path}"
        )

    indexer = AzureSearchIndexer()

    if ensure_index:
        indexer.create_or_update_index()

    uploaded_count = indexer.upload_documents_from_file(
        corpus_path=str(index_docs_path),
        batch_size=batch_size,
        kg_path=None,  # no graph bridge for uploaded docs in demo
    )

    return {
        "contractId": inferred_contract_id,
        "savedFile": str(saved_file_path),
        "indexDocsPath": str(index_docs_path),
        "uploadedToAzureSearch": uploaded_count,
        "graphWritten": False,
        "note": (
            "Uploaded contract was added to Azure AI Search only. "
            "Cosmos Gremlin graph upsertion is skipped for demo."
        ),
        "ingestionResult": ingestion_result,
    }


def pretty_json(data: Dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)