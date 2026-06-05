"""
Azure Blob Storage client for raw file and artifact persistence.

Container layout:
  uploads/<userId>/<jobId>/<filename>          — raw uploaded files
  artifacts/<contractId>/index_docs.json       — searchable chunks + embeddings
  artifacts/<contractId>/tree.json             — parsed document tree
  artifacts/<contractId>/chunks.json           — semantic chunks
"""

import io
import json
import logging
from typing import Any

from azure.storage.blob import BlobServiceClient, ContentSettings

from app import config

logger = logging.getLogger(__name__)

_UPLOADS_PREFIX = "uploads"
_ARTIFACTS_PREFIX = "artifacts"


class BlobStore:
    def __init__(self):
        self._client = BlobServiceClient.from_connection_string(
            config.AZURE_BLOB_CONNECTION_STRING
        )
        self._container = config.AZURE_BLOB_CONTAINER

    # ------------------------------------------------------------------
    # One-time setup (idempotent)
    # ------------------------------------------------------------------

    def ensure_container(self) -> None:
        container_client = self._client.get_container_client(self._container)
        if not container_client.exists():
            container_client.create_container()
            logger.info("Created blob container '%s'.", self._container)

    # ------------------------------------------------------------------
    # Raw file upload (called from API handler with in-memory bytes)
    # ------------------------------------------------------------------

    def upload_raw_file(
        self,
        user_id: str,
        job_id: str,
        filename: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        Upload raw file bytes. Returns the blob path (not a URL).
        """
        blob_path = f"{_UPLOADS_PREFIX}/{user_id}/{job_id}/{filename}"
        blob_client = self._client.get_blob_client(
            container=self._container, blob=blob_path
        )
        blob_client.upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )
        logger.info("Uploaded raw file to blob: %s", blob_path)
        return blob_path

    # ------------------------------------------------------------------
    # Artifact upload (called from worker after ingestion)
    # ------------------------------------------------------------------

    def upload_artifact(
        self, contract_id: str, artifact_name: str, data: Any
    ) -> str:
        """
        Serialize data as JSON and upload to artifacts/<contractId>/<name>.
        Returns the blob path.
        """
        blob_path = f"{_ARTIFACTS_PREFIX}/{contract_id}/{artifact_name}"
        blob_client = self._client.get_blob_client(
            container=self._container, blob=blob_path
        )
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        blob_client.upload_blob(
            io.BytesIO(payload),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json"),
        )
        logger.info("Uploaded artifact to blob: %s", blob_path)
        return blob_path

    # ------------------------------------------------------------------
    # Download helpers (used by worker)
    # ------------------------------------------------------------------

    def download_raw_file(self, blob_path: str) -> bytes:
        blob_client = self._client.get_blob_client(
            container=self._container, blob=blob_path
        )
        return blob_client.download_blob().readall()

    def download_artifact_json(self, contract_id: str, artifact_name: str) -> Any:
        blob_path = f"{_ARTIFACTS_PREFIX}/{contract_id}/{artifact_name}"
        blob_client = self._client.get_blob_client(
            container=self._container, blob=blob_path
        )
        raw = blob_client.download_blob().readall()
        return json.loads(raw.decode("utf-8"))

    def artifact_exists(self, contract_id: str, artifact_name: str) -> bool:
        blob_path = f"{_ARTIFACTS_PREFIX}/{contract_id}/{artifact_name}"
        blob_client = self._client.get_blob_client(
            container=self._container, blob=blob_path
        )
        return blob_client.exists()
