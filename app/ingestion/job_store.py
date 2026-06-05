"""
Cosmos DB NoSQL store for ingestion job tracking.

Container: ingest_jobs  (partition key = /userId)

Job document schema:
{
  "id":          <jobId>,
  "userId":      <str>,
  "contractId":  <str>,
  "fileName":    <str>,
  "blobPath":    <str>,          -- raw file location in Azure Blob
  "status":      "queued" | "processing" | "done" | "failed",
  "stage":       "uploading" | "parsing" | "embedding" | "indexing" | "done" | "error",
  "progress":    0-100,
  "createdAt":   <ISO-8601>,
  "updatedAt":   <ISO-8601>,
  "result":      { uploadedChunks, graphWritten } | null,
  "error":       <str> | null
}
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from azure.cosmos import CosmosClient, PartitionKey, exceptions

from app import config

logger = logging.getLogger(__name__)

_CONTAINER_NAME = "ingest_jobs"


class JobStore:
    def __init__(self):
        self._client = CosmosClient(
            url=config.COSMOS_NOSQL_ENDPOINT,
            credential=config.COSMOS_NOSQL_KEY,
        )
        self._db = self._client.get_database_client(config.COSMOS_NOSQL_DATABASE)
        self._container = self._db.get_container_client(_CONTAINER_NAME)

    # ------------------------------------------------------------------
    # One-time setup (idempotent)
    # ------------------------------------------------------------------

    def ensure_container(self) -> None:
        db = self._client.create_database_if_not_exists(config.COSMOS_NOSQL_DATABASE)
        db.create_container_if_not_exists(
            id=_CONTAINER_NAME,
            partition_key=PartitionKey(path="/userId"),
            offer_throughput=400,
        )
        self._db = db
        self._container = db.get_container_client(_CONTAINER_NAME)
        logger.info("Cosmos container '%s' ready.", _CONTAINER_NAME)

    # ------------------------------------------------------------------
    # Job lifecycle
    # ------------------------------------------------------------------

    def create_job(
        self,
        user_id: str,
        contract_id: str,
        file_name: str,
        blob_path: str,
    ) -> Dict[str, Any]:
        now = _now()
        job: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "userId": user_id,
            "contractId": contract_id,
            "fileName": file_name,
            "blobPath": blob_path,
            "status": "queued",
            "stage": "uploading",
            "progress": 5,
            "createdAt": now,
            "updatedAt": now,
            "result": None,
            "error": None,
        }
        self._container.create_item(body=job)
        return job

    def get_job(self, job_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self._container.read_item(item=job_id, partition_key=user_id)
        except exceptions.CosmosResourceNotFoundError:
            return None

    def list_jobs(self, user_id: str) -> List[Dict[str, Any]]:
        query = (
            "SELECT * FROM c WHERE c.userId = @uid "
            "ORDER BY c.createdAt DESC"
        )
        params = [{"name": "@uid", "value": user_id}]
        return list(
            self._container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=False,
            )
        )

    def update_stage(
        self,
        job_id: str,
        user_id: str,
        stage: str,
        progress: int,
        status: str = "processing",
    ) -> None:
        job = self.get_job(job_id, user_id)
        if job is None:
            return
        job["stage"] = stage
        job["progress"] = progress
        job["status"] = status
        job["updatedAt"] = _now()
        self._container.replace_item(item=job_id, body=job)

    def mark_done(
        self,
        job_id: str,
        user_id: str,
        result: Dict[str, Any],
    ) -> None:
        job = self.get_job(job_id, user_id)
        if job is None:
            return
        job["status"] = "done"
        job["stage"] = "done"
        job["progress"] = 100
        job["result"] = result
        job["error"] = None
        job["updatedAt"] = _now()
        self._container.replace_item(item=job_id, body=job)

    def mark_failed(self, job_id: str, user_id: str, error: str) -> None:
        job = self.get_job(job_id, user_id)
        if job is None:
            return
        job["status"] = "failed"
        job["stage"] = "error"
        job["progress"] = 0
        job["error"] = error
        job["updatedAt"] = _now()
        self._container.replace_item(item=job_id, body=job)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
