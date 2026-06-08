"""
Background ingestion worker.

Each job runs in a thread from a module-level ThreadPoolExecutor.

Flow per file:
  1. Download raw file from Azure Blob Storage
  2. Write to a temp file on local disk (ephemeral, cleaned up after)
  3. Run IngestionService with BlobArtifactStore
     → parse → tree → chunk → embed → summary
     → artifacts written to Blob (not local disk)
  4. Upload index_docs directly to Azure AI Search
  5. KG pipeline (only when GREMLIN_ENDPOINT is configured):
     → normalize tree → write structural graph to Gremlin
     → select representative clauses → LLM extraction
     → write semantic entities/relations to Gremlin
  6. Mark job done in Cosmos

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


def _run_kg_pipeline(
    contract_id: str,
    tree_dict: dict,
    job_id: str,
    user_id: str,
    job_store: "JobStore",
) -> bool:
    """
    Normalize tree (for clause selection) → LLM extract clauses →
    write legal-semantic graph to Gremlin.

    The structural graph is intentionally NOT written to Gremlin — the
    document hierarchy already lives in the tree JSON (Blob) and is used
    by SemanticRetriever for tree-context expansion. Clause citation
    metadata (title, page range) is denormalized directly onto each legal
    entity at write time, so no structural clause vertices are needed.

    Returns True if graph was written, False if skipped or failed.
    Non-fatal: caller continues to mark_done even on failure.
    """
    from app.kg.gremlin_writer import GremlinWriter, gremlin_is_configured
    from app.kg.normalize_tree import normalize_contract_tree_from_dict
    from app.kg.legal_extractor import LegalLLMExtractor
    from app.kg.clause_selector import select_representative_clauses

    if not gremlin_is_configured():
        logger.info("Job %s: Gremlin not configured, skipping KG pipeline.", job_id)
        return False

    try:
        job_store.update_stage(job_id, user_id, stage="extracting", progress=75)
        logger.info("Job %s: normalizing tree for %s", job_id, contract_id)
        # Normalize only to obtain clause nodes for selection — not written to Gremlin.
        normalized = normalize_contract_tree_from_dict(tree_dict, contract_id)

        writer = GremlinWriter()
        try:
            # Select clauses and run LLM extraction
            job_store.update_stage(job_id, user_id, stage="extracting", progress=82)
            clauses = select_representative_clauses(normalized.nodes)
            logger.info("Job %s: extracting KG from %d clauses", job_id, len(clauses))

            extractor = LegalLLMExtractor()
            extractions = []
            for clause in clauses:
                try:
                    result = extractor.extract_from_clause(clause)
                    extractions.append(result)
                except Exception as e:
                    logger.warning("Job %s: extraction failed for clause %s: %s", job_id, clause.kgId, e)

            # Write semantic entities and relations to Gremlin
            job_store.update_stage(job_id, user_id, stage="graph_writing", progress=90)
            for extraction in extractions:
                try:
                    writer.write_legal_extraction(extraction, config.TENANT_ID, contract_id)
                except Exception as e:
                    logger.warning("Job %s: Gremlin write failed for extraction: %s", job_id, e)

            logger.info(
                "Job %s: KG pipeline done — %d extractions written to Gremlin",
                job_id, len(extractions),
            )
            return True

        finally:
            writer.close()

    except Exception as exc:
        logger.error("Job %s: KG pipeline failed (non-fatal): %s", job_id, exc)
        return False


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

        # ── Step 3: parse → tree → chunk → embed → summary ───────────
        blob_artifact_store = BlobArtifactStore(blob_store=blob_store)
        ingestion_svc = IngestionService(store=blob_artifact_store)

        job_store.update_stage(job_id, user_id, stage="parsing", progress=20)
        ingestion_result = ingestion_svc.ingest_file(
            file_path=tmp_path,
            contract_id=contract_id,
        )

        # ── Step 4: upload index_docs to Azure AI Search ──────────────
        index_docs = ingestion_result.get("index_docs", [])
        if not index_docs:
            raise ValueError(f"No index_docs returned from ingestion for {contract_id}")

        job_store.update_stage(job_id, user_id, stage="embedding", progress=55)
        job_store.update_stage(job_id, user_id, stage="indexing", progress=70)
        indexer = AzureSearchIndexer()
        uploaded_count = indexer.upload_documents(index_docs, kg_lookup=None)

        # ── Step 5: KG extraction + Gremlin write (if configured) ─────
        tree_dict = ingestion_result.get("tree_dict", {})
        graph_written = _run_kg_pipeline(contract_id, tree_dict, job_id, user_id, job_store)

        # ── Step 6: mark done ─────────────────────────────────────────
        job_store.mark_done(
            job_id=job_id,
            user_id=user_id,
            result={
                "contractId": contract_id,
                "uploadedChunks": uploaded_count,
                "graphWritten": graph_written,
                "ingestionManifest": ingestion_result.get("manifest", {}),
            },
        )
        logger.info(
            "Job %s completed: %d chunks indexed, graphWritten=%s for %s.",
            job_id, uploaded_count, graph_written, contract_id,
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
