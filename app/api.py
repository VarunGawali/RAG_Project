"""
FastAPI backend for Contract360.

Endpoints
---------
POST   /sessions                     Create a new chat session
GET    /sessions                     List sessions for a user
GET    /sessions/{session_id}        Get session metadata + messages
DELETE /sessions/{session_id}        Delete a session
POST   /sessions/{session_id}/ask    Ask a question (saves history, returns answer)

POST   /ingest                       Upload one or more files (multipart); returns job IDs
GET    /ingest/{job_id}/status       Poll ingestion job status

GET    /health                       Liveness check

Authentication
--------------
For now we use a simple header `X-User-Id` (defaults to "default_user").
This is intentionally minimal — swap in Azure Entra ID when auth is added.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.chat_history.session_service import SessionService
from app.ingestion.job_store import JobStore
from app.ingestion import worker as ingestion_worker
from app.indexing.search_tester import AzureSearchTester
from app.rag.query_service import answer_question
from app.services.frontend_ingestion_service import sanitize_contract_id
from app.storage.blob_store import BlobStore

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Contract360 API", version="1.0.0")

# Allow the React dev server (port 5173) and any same-origin requests.
# Restrict origins in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_session_svc = SessionService()
_job_store   = JobStore()
_blob_store  = BlobStore()

_MAX_FILE_BYTES = 50 * 1024 * 1024   # 50 MB per file
_ALLOWED_EXTS   = {".pdf", ".txt", ".md"}


# ──────────────────────────────────────────────
# Request / Response models
# ──────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    contract_filter: Optional[str] = None


class AskRequest(BaseModel):
    question: str
    top: int = 4
    route_override: str = "auto"
    return_context: bool = False
    contract_ids: Optional[List[str]] = None   # multi-contract filter; overrides session contractFilter


class AskResponse(BaseModel):
    session_id: str
    message_id: str
    route: str
    reason: str
    rewritten_query: Optional[str] = None
    answer: str
    context: Optional[str] = None


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _get_user(x_user_id: Optional[str]) -> str:
    """Return caller's user id, defaulting to 'default_user' for demo mode."""
    return (x_user_id or "default_user").strip() or "default_user"


def _require_session(session_id: str, user_id: str):
    session = _session_svc.get(session_id, user_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
    return session


# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(
    body: CreateSessionRequest,
    x_user_id: Optional[str] = Header(default=None),
):
    user_id = _get_user(x_user_id)
    session = _session_svc.create(
        user_id=user_id,
        contract_filter=body.contract_filter,
    )
    return session


@app.get("/sessions")
def list_sessions(x_user_id: Optional[str] = Header(default=None)):
    user_id = _get_user(x_user_id)
    return _session_svc.list_all(user_id)


@app.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    x_user_id: Optional[str] = Header(default=None),
):
    user_id = _get_user(x_user_id)
    return _require_session(session_id, user_id)


@app.get("/sessions/{session_id}/history")
def get_history(
    session_id: str,
    x_user_id: Optional[str] = Header(default=None),
):
    user_id = _get_user(x_user_id)
    _require_session(session_id, user_id)
    messages = _session_svc.get_history(session_id, user_id)
    # Rename 'sources' → 'citations' to match the frontend Message type
    for msg in messages:
        if "sources" in msg:
            msg["citations"] = msg.pop("sources")
    return messages


@app.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    x_user_id: Optional[str] = Header(default=None),
):
    user_id = _get_user(x_user_id)
    deleted = _session_svc.delete(session_id, user_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )


@app.post("/sessions/{session_id}/ask")
def ask(
    session_id: str,
    body: AskRequest,
    x_user_id: Optional[str] = Header(default=None),
) -> AskResponse:
    user_id = _get_user(x_user_id)
    session = _require_session(session_id, user_id)

    # 1. Persist the user message
    user_msg = _session_svc.save_user_message(
        session_id=session_id,
        user_id=user_id,
        content=body.question,
    )

    # 2. Build history slice for the LLM (excludes the message just saved)
    chat_history = _session_svc.build_llm_history(session_id, user_id)
    # The last entry in history is now the user message we just saved.
    # Drop it — answer_question appends the current question itself.
    if chat_history and chat_history[-1]["role"] == "user":
        chat_history = chat_history[:-1]

    # 3. Run RAG
    # contract_ids from request body takes precedence over session contractFilter
    contract_filter = session.get("contractFilter")
    result = answer_question(
        question=body.question,
        contract_id=contract_filter,
        contract_ids=body.contract_ids or None,
        top=body.top,
        route_override=body.route_override,
        return_context=body.return_context,
        chat_history=chat_history,
    )

    # 4. Persist the assistant message
    assistant_msg = _session_svc.save_assistant_message(
        session_id=session_id,
        user_id=user_id,
        content=result["answer"],
        route=result["route"],
    )

    return AskResponse(
        session_id=session_id,
        message_id=assistant_msg["id"],
        route=result["route"],
        reason=result["reason"],
        rewritten_query=result.get("rewritten_query"),
        answer=result["answer"],
        context=result.get("context"),
    )


# ──────────────────────────────────────────────
# Ingestion routes
# ──────────────────────────────────────────────

class IngestJobResponse(BaseModel):
    jobId: str
    contractId: str
    fileName: str
    status: str
    stage: str
    progress: int


class IngestJobStatusResponse(BaseModel):
    jobId: str
    contractId: str
    fileName: str
    status: str
    stage: str
    progress: int
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


@app.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_files(
    files: List[UploadFile] = File(...),
    x_user_id: Optional[str] = Header(default=None),
) -> List[IngestJobResponse]:
    """
    Accept one or more documents, upload raw bytes to Azure Blob Storage,
    create a job record in Cosmos, enqueue background ingestion, and return
    job IDs immediately (HTTP 202 Accepted).

    The caller polls GET /ingest/{jobId}/status to track progress.
    """
    user_id = _get_user(x_user_id)

    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided.",
        )

    responses: List[IngestJobResponse] = []

    for upload in files:
        filename = upload.filename or "document"
        ext = _file_extension(filename)

        if ext not in _ALLOWED_EXTS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported file type '{ext}'. Allowed: PDF, TXT, MD.",
            )

        raw_bytes = await upload.read()

        if len(raw_bytes) > _MAX_FILE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"'{filename}' exceeds the 50 MB limit.",
            )

        # Derive contract ID from filename
        contract_id = sanitize_contract_id(
            re.sub(r"\.[^.]+$", "", filename)
        )

        # Upload raw file to Blob Storage
        job_id_placeholder = _blob_store._client.get_container_client(
            _blob_store._container
        )   # just to get the client reference — actual job_id comes next

        # Create job record first to get the real job ID
        job = _job_store.create_job(
            user_id=user_id,
            contract_id=contract_id,
            file_name=filename,
            blob_path="",   # filled in below after we have the job ID
        )
        job_id = job["id"]

        # Now upload with the real job ID in the path
        content_type = upload.content_type or "application/octet-stream"
        blob_path = _blob_store.upload_raw_file(
            user_id=user_id,
            job_id=job_id,
            filename=filename,
            data=raw_bytes,
            content_type=content_type,
        )

        # Patch blob_path into job record
        job["blobPath"] = blob_path
        _job_store._container.replace_item(item=job_id, body=job)

        # Enqueue background worker
        ingestion_worker.enqueue(
            job_id=job_id,
            user_id=user_id,
            contract_id=contract_id,
            blob_path=blob_path,
            file_name=filename,
        )

        responses.append(
            IngestJobResponse(
                jobId=job_id,
                contractId=contract_id,
                fileName=filename,
                status=job["status"],
                stage=job["stage"],
                progress=job["progress"],
            )
        )

    return responses


@app.get("/ingest/{job_id}/status")
def get_ingest_status(
    job_id: str,
    x_user_id: Optional[str] = Header(default=None),
) -> IngestJobStatusResponse:
    user_id = _get_user(x_user_id)
    job = _job_store.get_job(job_id, user_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )
    return IngestJobStatusResponse(
        jobId=job["id"],
        contractId=job["contractId"],
        fileName=job["fileName"],
        status=job["status"],
        stage=job["stage"],
        progress=job["progress"],
        error=job.get("error"),
        result=job.get("result"),
    )


@app.get("/ingest")
def list_ingest_jobs(
    x_user_id: Optional[str] = Header(default=None),
) -> List[IngestJobStatusResponse]:
    user_id = _get_user(x_user_id)
    jobs = _job_store.list_jobs(user_id)
    return [
        IngestJobStatusResponse(
            jobId=j["id"],
            contractId=j["contractId"],
            fileName=j["fileName"],
            status=j["status"],
            stage=j["stage"],
            progress=j["progress"],
            error=j.get("error"),
            result=j.get("result"),
        )
        for j in jobs
    ]


# ──────────────────────────────────────────────
# Contracts route
# ──────────────────────────────────────────────

class ContractSummary(BaseModel):
    id: str
    displayName: str


@app.get("/contracts")
def list_contracts() -> List[ContractSummary]:
    """Return all contract IDs currently indexed in Azure AI Search."""
    searcher = AzureSearchTester()
    ids = searcher.list_contract_ids()
    return [
        ContractSummary(
            id=cid,
            displayName=cid.replace("_", " "),
        )
        for cid in ids
    ]


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _file_extension(filename: str) -> str:
    from pathlib import Path
    return Path(filename).suffix.lower()