"""
Blob-backed artifact store.

Mirrors the ArtifactStore interface so IngestionService and the
worker can swap implementations via get_artifact_store().

Blob layout (under the same container as BlobStore):
  artifacts/<contractId>/raw_text.txt
  artifacts/<contractId>/tree.json
  artifacts/<contractId>/chunks.json
  artifacts/<contractId>/index_docs.json
  artifacts/<contractId>/manifest.json
"""

import json
import logging
from typing import Any, Dict, List, Optional

from app.storage.blob_store import BlobStore

logger = logging.getLogger(__name__)


class BlobArtifactStore:
    def __init__(self, blob_store: Optional[BlobStore] = None):
        self._blob = blob_store or BlobStore()

    # ------------------------------------------------------------------
    # Write path  (called by IngestionService)
    # ------------------------------------------------------------------

    def save_contract_artifacts(
        self,
        contract_id: str,
        raw_text: str,
        tree: Dict,
        chunks: List[Dict],
        index_docs: List[Dict],
        source_file: str,
    ) -> Dict:
        manifest = {
            "contractId": contract_id,
            "sourceFile": source_file,
            "chunkCount": len(chunks),
            "indexDocCount": len(index_docs),
        }

        # Upload raw text as plain bytes
        self._blob._client.get_blob_client(
            container=self._blob._container,
            blob=f"artifacts/{contract_id}/raw_text.txt",
        ).upload_blob(
            raw_text.encode("utf-8"),
            overwrite=True,
        )

        self._blob.upload_artifact(contract_id, "tree.json", tree)
        self._blob.upload_artifact(contract_id, "chunks.json", chunks)
        self._blob.upload_artifact(contract_id, "index_docs.json", index_docs)
        self._blob.upload_artifact(contract_id, "manifest.json", manifest)

        logger.info(
            "Saved %d index docs for '%s' to Blob.", len(index_docs), contract_id
        )
        return manifest

    def rebuild_corpus_files(self) -> Dict:
        """No-op for Blob storage — corpus aggregation is not needed in cloud."""
        return {}

    # ------------------------------------------------------------------
    # Read path  (called by SemanticRetriever, worker, etc.)
    # ------------------------------------------------------------------

    def get_tree(self, contract_id: str) -> Optional[Dict]:
        """Download and return tree.json for a contract. Returns None if missing."""
        if not self._blob.artifact_exists(contract_id, "tree.json"):
            return None
        return self._blob.download_artifact_json(contract_id, "tree.json")

    def get_index_docs(self, contract_id: str) -> Optional[List[Dict]]:
        """Download and return index_docs.json for a contract. Returns None if missing."""
        if not self._blob.artifact_exists(contract_id, "index_docs.json"):
            return None
        return self._blob.download_artifact_json(contract_id, "index_docs.json")

    def get_chunks(self, contract_id: str) -> Optional[List[Dict]]:
        if not self._blob.artifact_exists(contract_id, "chunks.json"):
            return None
        return self._blob.download_artifact_json(contract_id, "chunks.json")

    def get_manifest(self, contract_id: str) -> Optional[Dict]:
        if not self._blob.artifact_exists(contract_id, "manifest.json"):
            return None
        return self._blob.download_artifact_json(contract_id, "manifest.json")

    def save_summary(self, contract_id: str, summary: Dict) -> None:
        self._blob.upload_artifact(contract_id, "summary.json", summary)
        logger.info("Saved summary for '%s' to Blob.", contract_id)

    def load_summary(self, contract_id: str) -> Optional[Dict]:
        if not self._blob.artifact_exists(contract_id, "summary.json"):
            return None
        return self._blob.download_artifact_json(contract_id, "summary.json")

    def get_kg_normalized(self, contract_id: str) -> Optional[Dict]:
        """
        Download the pre-built normalized KG JSON for a contract.
        Uploaded by app/scripts/upload_artifacts_to_blob.py from
        /data/kg/normalized/<contractId>_kg_ready.json.
        """
        if not self._blob.artifact_exists(contract_id, "kg_normalized.json"):
            return None
        return self._blob.download_artifact_json(contract_id, "kg_normalized.json")