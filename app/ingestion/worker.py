"""
Background ingestion worker.

Each job runs in a thread from a module-level ThreadPoolExecutor.

Flow per file:
  1. Download raw file from Azure Blob Storage
  2. Write to a temp file on local disk (ephemeral, cleaned up after)
  3. Run IngestionService with BlobArtifactStore
     → parse → tree → chunk → embed
     → artifacts written to Blob (not local disk)
  4. Upload index_docs directly to Azure AI Search (no local file read)
  5. Mark job done in Cosmos

NOTE: For higher throughput or multi-instance deployments, replace the
ThreadPoolExecutor with an Azure Service Bus queue + a dedicated worker
process that calls run_job() after dequeuing a message.
"""

import logging
import os
import tempfile
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import config
from app.ingestion.job_store import JobStore
from app.services.ingestion_service import IngestionService
from app.indexing.azure_search_uploader import AzureSearchIndexer
from app.storage.blob_store import BlobStore
from app.storage.blob_artifact_store import BlobArtifactStore

logger = logging.getLogger(__name__)

# Max concurrent ingestion jobs. Keep low — each job calls Azure OpenAI for
# embeddings and can be memory-intensive for large PDFs.
_EXECUTOR = ThreadPoolExecutor(max_workers=4)


def enqueue(
    job_id: str,
    user_id: str,
    contract_id: str,
    blob_path: str,
    file_name: str,
) -> None:
    """Submit a job to the thread pool. Returns immediately."""
    _EXECUTOR.submit(_run_job, job_id, user_id, contract_id, blob_path, file_name)


def _run_job(
    job_id: str,
    user_id: str,
    contract_id: str,
    blob_path: str,
    file_name: str,
) -> None:
    job_store = JobStore()
    blob_store = BlobStore()
    suffix = Path(file_name).suffix.lower() or ".pdf"

    tmp_path: str | None = None

    try:
        # ── Step 1: download raw file from Blob ───────────────────────
        job_store.update_stage(job_id, user_id, stage="parsing", progress=10)
        raw_bytes = blob_store.download_raw_file(blob_path)

        # ── Step 2: write to ephemeral temp file ──────────────────────
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        try:
            os.write(fd, raw_bytes)
        finally:
            os.close(fd)

        # ── Step 3: parse → tree → chunk → embed ─────────────────────
        # Use BlobArtifactStore so artifacts go to Blob, not local disk.
        blob_artifact_store = BlobArtifactStore(blob_store=blob_store)
        ingestion_svc = IngestionService(store=blob_artifact_store)

        job_store.update_stage(job_id, user_id, stage="parsing", progress=20)
        ingestion_result = ingestion_svc.ingest_file(
            file_path=tmp_path,
            contract_id=contract_id,
        )

        # ── Step 4: upload index_docs to Azure AI Search ──────────────
        # index_docs is returned directly by ingest_file — no disk read.
        index_docs = ingestion_result.get("index_docs", [])
        if not index_docs:
            raise ValueError(
                f"No index_docs returned from ingestion for {contract_id}"
            )

        job_store.update_stage(job_id, user_id, stage="embedding", progress=55)
        job_store.update_stage(job_id, user_id, stage="indexing", progress=70)
        indexer = AzureSearchIndexer()
        uploaded_count = indexer.upload_documents(index_docs, kg_lookup=None)

        # ── Step 5: mark done ─────────────────────────────────────────
        job_store.mark_done(
            job_id=job_id,
            user_id=user_id,
            result={
                "contractId": contract_id,
                "uploadedChunks": uploaded_count,
                "graphWritten": False,
                "ingestionManifest": ingestion_result.get("manifest", {}),
            },
        )
        logger.info(
            "Job %s completed: %d chunks indexed for %s.",
            job_id, uploaded_count, contract_id,
        )

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        logger.error("Job %s failed: %s", job_id, error_msg)
        job_store.mark_failed(job_id=job_id, user_id=user_id, error=str(exc))

    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass