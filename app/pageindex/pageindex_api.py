"""
PageIndex API tree generator.

Two implementations:
- PageIndexApiTreeGenerator  — writes to local disk (legacy / local dev)
- BlobPageIndexTreeGenerator — writes to Azure Blob Storage (production)

IngestionService selects the right one based on USE_BLOB_ARTIFACTS config.
"""

import json
import time
from pathlib import Path
from typing import Optional

from app import config


class PageIndexApiTreeGenerator:
    """
    Uses the hosted PageIndex API to generate a tree JSON for a PDF.
    Writes the result to local disk: samples/pageindex_trees/{contract_id}.json
    Used in local development mode (USE_BLOB_ARTIFACTS=false).
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or config.PAGEINDEX_OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def output_path(self, contract_id: str) -> Path:
        return self.output_dir / f"{contract_id}.json"

    def exists(self, contract_id: str) -> bool:
        return self.output_path(contract_id).exists()

    def generate(
        self,
        file_path: str,
        contract_id: str,
        force: bool = False,
    ) -> Optional[str]:
        """Returns the local file path string on success, None on failure."""
        output_path = self.output_path(contract_id)

        if output_path.exists() and not force:
            print(f"[PageIndex] Existing tree found: {output_path}")
            return str(output_path)

        tree_data = _call_pageindex_api(file_path, contract_id)
        if tree_data is None:
            return None

        output_path.write_text(
            json.dumps(tree_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[PageIndex] Tree saved locally: {output_path}")
        return str(output_path)


class BlobPageIndexTreeGenerator:
    """
    Uses the hosted PageIndex API to generate a tree JSON for a PDF.
    Writes the result to Azure Blob Storage: artifacts/{contractId}/pageindex_tree.json
    Used in cloud mode (USE_BLOB_ARTIFACTS=true).
    """

    def __init__(self):
        from app.storage.blob_store import BlobStore
        self._blob = BlobStore()

    def exists(self, contract_id: str) -> bool:
        return self._blob.artifact_exists(contract_id, "pageindex_tree.json")

    def generate(
        self,
        file_path: str,
        contract_id: str,
        force: bool = False,
    ) -> Optional[str]:
        """
        Returns the Blob path string on success, None on failure.
        The blob path can be passed to load_pageindex_tree_from_blob().
        """
        if self.exists(contract_id) and not force:
            print(f"[PageIndex] Cached tree found in Blob for: {contract_id}")
            blob_path = f"artifacts/{contract_id}/pageindex_tree.json"
            return blob_path

        tree_data = _call_pageindex_api(file_path, contract_id)
        if tree_data is None:
            return None

        blob_path = self._blob.upload_artifact(
            contract_id, "pageindex_tree.json", tree_data
        )
        print(f"[PageIndex] Tree saved to Blob: {blob_path}")
        return blob_path

    def get_tree_data(self, contract_id: str) -> Optional[dict]:
        """Download and return the tree data from Blob."""
        if not self.exists(contract_id):
            return None
        return self._blob.download_artifact_json(contract_id, "pageindex_tree.json")


def get_pageindex_generator():
    """Return the right PageIndex generator based on config."""
    if config.USE_BLOB_ARTIFACTS:
        return BlobPageIndexTreeGenerator()
    return PageIndexApiTreeGenerator()


# ------------------------------------------------------------------
# Shared API call logic
# ------------------------------------------------------------------

def _call_pageindex_api(file_path: str, contract_id: str) -> Optional[dict]:
    """
    Submit a document to the PageIndex API, poll until complete, and
    return the raw tree dict. Returns None on any failure.
    """
    if not config.PAGEINDEX_API_KEY:
        print("[PageIndex] PAGEINDEX_API_KEY missing. Skipping PageIndex.")
        return None

    try:
        from app.pageindex import PageIndexClient
    except Exception as exc:
        print("[PageIndex] pageindex package not installed or import failed.")
        print(exc)
        return None

    print(f"[PageIndex] Submitting document: {file_path}")
    client = PageIndexClient(api_key=config.PAGEINDEX_API_KEY)

    try:
        submit_result = client.submit_document(file_path)
        doc_id = submit_result["doc_id"]
        print(f"[PageIndex] Submitted. doc_id={doc_id}")
    except Exception as exc:
        print("[PageIndex] submit_document failed.")
        print(exc)
        return None

    status = None
    for attempt in range(config.PAGEINDEX_MAX_POLLS):
        try:
            doc = client.get_document(doc_id)
            status = doc.get("status")
            print(
                f"[PageIndex] Poll {attempt + 1}/{config.PAGEINDEX_MAX_POLLS}: "
                f"status={status}"
            )
            if status == "completed":
                break
            if status in {"failed", "error"}:
                print("[PageIndex] Processing failed.")
                return None
        except Exception as exc:
            print("[PageIndex] get_document failed.")
            print(exc)
        time.sleep(config.PAGEINDEX_POLL_SECONDS)

    if status != "completed":
        print("[PageIndex] Timed out waiting for processing.")
        return None

    try:
        tree_result = client.get_tree(doc_id)
        tree = tree_result.get("result", tree_result)
    except Exception as exc:
        print("[PageIndex] get_tree failed.")
        print(exc)
        return None

    return {
        "provider":   "pageindex_api",
        "doc_id":     doc_id,
        "contractId": contract_id,
        "tree":       tree,
    }
