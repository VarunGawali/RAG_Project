"""
Background ingestion worker.

Each job runs in a thread from a module-level ThreadPoolExecutor.

Flow per file:
  1. Download raw file from Azure Blob Storage
  2. Write to a temp file on local disk (ephemeral, cleaned up after)
  3. Run IngestionService (parse → tree → chunk → embed)
  4. Upload index_docs to Azure AI Search
  5. Persist key artifacts back to Azure Blob
  6. Mark job done in Cosmos

NOTE: For higher throughput or multi-instance deployments, replace the
ThreadPoolExecutor with an Azure Service Bus queue + a dedicated worker
process that calls run_job() after dequeuing a message.
"""

import json
import logging
import tempfile
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict

from app import config
from app.ingestion.job_store import JobStore
from app.services.ingestion_service import IngestionService
from app.indexing.azure_search_uploader import AzureSearchIndexer
from app.storage.blob_store import BlobStore

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
        # ── Step 1: download from Blob ─────────────────────────────────
        job_store.update_stage(job_id, user_id, stage="parsing", progress=10)
        raw_bytes = blob_store.download_raw_file(blob_path)

        # ── Step 2: write to a temp file ───────────────────────────────
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        try:
            import os
            os.write(fd, raw_bytes)
        finally:
            import os
            os.close(fd)

        # ── Step 3: parse → tree → chunk ──────────────────────────────
        job_store.update_stage(job_id, user_id, stage="parsing", progress=20)
        ingestion_svc = IngestionService()
        ingestion_result = ingestion_svc.ingest_file(
            file_path=tmp_path,
            contract_id=contract_id,
        )

        # ── Step 4: embed + upload to Azure AI Search ─────────────────
        job_store.update_stage(job_id, user_id, stage="embedding", progress=55)

        index_docs_path = config.PROCESSED_DIR / contract_id / "index_docs.json"
        if not index_docs_path.exists():
            raise FileNotFoundError(
                f"index_docs.json not found after ingestion: {index_docs_path}"
            )

        with open(index_docs_path, "r", encoding="utf-8") as f:
            index_docs = json.load(f)

        job_store.update_stage(job_id, user_id, stage="indexing", progress=70)
        indexer = AzureSearchIndexer()
        uploaded_count = indexer.upload_documents(index_docs, kg_lookup=None)

        # ── Step 5: persist artifacts to Blob ─────────────────────────
        job_store.update_stage(job_id, user_id, stage="indexing", progress=88)
        _persist_artifacts(blob_store, contract_id, index_docs_path)

        # ── Step 6: mark done ─────────────────────────────────────────
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


def _persist_artifacts(
    blob_store: BlobStore,
    contract_id: str,
    index_docs_path: Path,
) -> None:
    """
    Upload key processed artifacts to Blob so they survive container restarts.
    Only uploads files that actually exist.
    """
    artifact_files: Dict[str, Path] = {
        "index_docs.json": index_docs_path,
        "tree.json":       index_docs_path.parent / "tree.json",
        "chunks.json":     index_docs_path.parent / "chunks.json",
        "manifest.json":   index_docs_path.parent / "manifest.json",
    }

    for artifact_name, path in artifact_files.items():
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                blob_store.upload_artifact(contract_id, artifact_name, data)
            except Exception as exc:
                logger.warning(
                    "Could not persist artifact %s for %s: %s",
                    artifact_name, contract_id, exc,
                )
