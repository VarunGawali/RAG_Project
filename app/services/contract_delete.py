"""
Delete a contract everywhere: Azure AI Search, Cosmos Gremlin, Blob, and jobs.

Each step is best-effort and isolated — a failure in one store does not block
the others. Returns a summary so the caller can report partial success.
"""

import logging
import time
from typing import Dict, Optional

from app import config

logger = logging.getLogger(__name__)


def _gremlin_configured() -> bool:
    return all([
        getattr(config, "GREMLIN_ENDPOINT", None),
        getattr(config, "GREMLIN_USERNAME", None),
        getattr(config, "GREMLIN_PASSWORD", None),
    ])


def _drop_graph_for_contract(contract_id: str, batch: int = 25, delay: float = 0.3) -> int:
    """Batched drop of all vertices tagged with this contractId (edges cascade)."""
    from app.kg.gremlin_writer import GremlinWriter

    writer = GremlinWriter()
    dropped = 0
    try:
        # count first (best-effort)
        try:
            cnt = writer.submit("g.V().has('contractId', cid).count()", {"cid": contract_id})
            dropped = cnt[0] if cnt else 0
        except Exception:
            dropped = 0

        backoff = 1.0
        while True:
            try:
                writer.submit(
                    f"g.V().has('contractId', cid).limit({batch}).drop()",
                    {"cid": contract_id},
                )
                backoff = 1.0
            except Exception as e:
                msg = str(e)
                if "429" in msg or "TooManyRequests" in msg:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 20.0)
                    continue
                logger.warning("graph drop error for %s: %s", contract_id, e)
                break
            try:
                remaining = writer.submit(
                    "g.V().has('contractId', cid).limit(1).count()", {"cid": contract_id}
                )
            except Exception:
                remaining = [0]
            if not remaining or remaining[0] == 0:
                break
            if delay:
                time.sleep(delay)
    finally:
        writer.close()
    return dropped


def delete_contract(contract_id: str, user_id: Optional[str] = None) -> Dict:
    """
    Remove a contract from all stores. Returns a per-store summary.
    """
    summary: Dict[str, object] = {"contractId": contract_id}

    # 1. Azure AI Search
    try:
        from app.indexing.search_tester import AzureSearchTester
        summary["searchDocsDeleted"] = AzureSearchTester().delete_by_contract(contract_id)
    except Exception as exc:
        logger.error("Search delete failed for %s: %s", contract_id, exc)
        summary["searchError"] = str(exc)

    # 2. Cosmos Gremlin (semantic graph)
    if _gremlin_configured():
        try:
            summary["graphVerticesDeleted"] = _drop_graph_for_contract(contract_id)
        except Exception as exc:
            logger.error("Graph delete failed for %s: %s", contract_id, exc)
            summary["graphError"] = str(exc)
    else:
        summary["graphSkipped"] = "gremlin not configured"

    # 3. Blob artifacts (artifacts/<contractId>/*) + raw uploads (per job)
    try:
        from app.storage.blob_store import BlobStore
        blob = BlobStore()
        summary["artifactBlobsDeleted"] = blob.delete_contract_artifacts(contract_id)

        raw_deleted = 0
        if user_id:
            from app.ingestion.job_store import JobStore
            jobs = JobStore().list_jobs(user_id)
            for j in jobs:
                if j.get("contractId") == contract_id and j.get("blobPath"):
                    if blob.delete_blob(j["blobPath"]):
                        raw_deleted += 1
        summary["rawBlobsDeleted"] = raw_deleted
    except Exception as exc:
        logger.error("Blob delete failed for %s: %s", contract_id, exc)
        summary["blobError"] = str(exc)

    logger.info("Deleted contract %s: %s", contract_id, summary)
    return summary