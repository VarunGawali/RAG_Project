"""
Query service for Contract360.

Routes a question to one of four retrieval paths:
  search  — Azure AI Search (text / structural)
  graph   — Cosmos Gremlin native facts
  hybrid  — Azure AI Search + Cosmos Gremlin expansion
  tree    — Azure AI Search + hierarchical tree context (TreeRAG)

Routing is performed by an LLM classifier (query_router.py) with a
keyword-based fallback. The router also produces a rewritten_query
(pronouns resolved, context from chat history folded in) and a
structural_scope that replaces the old extract_structural_scope regex.
"""

from typing import Dict, List, Optional

from app.indexing.search_tester import AzureSearchTester
from app.rag.query_router import route_question
from app.rag.graph_retriever import graph_native_retrieve
from app.rag.hybrid_retriever import graph_rag_retrieve
from app.rag.answer_generator import AnswerGenerator
from app.rag.summary_generator import format_summary_as_answer
from app.services.prompt_builder import build_rag_prompt
from app.storage.artifact_store import get_artifact_store
from app.tree.semantic_retriever import SemanticRetriever


GRAPH_ENABLED_CONTRACTS = {
    "Edison_NYPA_OandM_Contract_1",
}


# ── Document-level summary shortcut ───────────────────────────────────────────

_SUMMARY_PATTERNS = {
    "what is this contract about", "what's this contract about",
    "what is this agreement about", "what's this agreement about",
    "tell me about this contract", "tell me about this agreement",
    "what does this contract cover", "what does this agreement cover",
    "give me a summary", "provide a summary", "contract overview",
    "give me an overview", "overview of this contract", "overview of the contract",
    "high-level summary", "high level summary",
    "summarize this contract", "summarise this contract",
    "summary of this contract", "summary of the contract",
    "summarize the contract", "summarise the contract",
    "summarize this agreement", "summarise this agreement",
    "summary of this agreement", "summary of the agreement",
}


def _is_summary_query(question: str) -> bool:
    """Return True only for whole-document summary intent, not section-specific queries."""
    q = question.lower().strip()
    return any(pat in q for pat in _SUMMARY_PATTERNS)


# ── Retrieval helpers ──────────────────────────────────────────────────────────

def _format_search_docs(docs: list) -> str:
    if not docs:
        return "No Azure AI Search results found."
    parts = []
    for idx, doc in enumerate(docs, start=1):
        parts += [
            "=" * 80,
            f"SEARCH RESULT {idx}",
            "=" * 80,
            f"Title: {doc.get('title')}",
            f"Section: {doc.get('sectionTitle')}",
            f"Pages: {doc.get('pageStart')}-{doc.get('pageEnd')}",
            f"Source path: {doc.get('sourcePath')}",
            f"kgId: {doc.get('kgId')}",
            "",
            doc.get("text") or "",
            "",
        ]
    return "\n".join(parts)


def _search_retrieve(
    question: str,
    contract_id: Optional[str],
    top: int,
    structural_scope: Optional[Dict],
) -> str:
    searcher = AzureSearchTester()

    if structural_scope:
        docs = searcher.retrieve_structural_scope(
            structure_type=structural_scope["type"],
            identifier=structural_scope["identifier"],
            contract_id=contract_id,
            top=100,
        )
        return _format_search_docs(docs)

    docs = searcher.hybrid_search(
        query=question,
        contract_id=contract_id,
        top=top,
    )
    return _format_search_docs(docs)


def _tree_retrieve(
    question: str,
    contract_id: Optional[str],
    top: int,
) -> str:
    retriever = SemanticRetriever(contract_id=contract_id)
    chunks = retriever.retrieve(query=question, top_k=top, contract_id=contract_id)
    return build_rag_prompt(query=question, retrieved_chunks=chunks)


# ── Main entry point ───────────────────────────────────────────────────────────

def answer_question(
    question: str,
    contract_id: Optional[str],
    top: int = 4,
    route_override: str = "auto",
    return_context: bool = False,
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> Dict:
    """
    Route, retrieve, and answer a question.

    Returns
    -------
    {
      "route":   str,
      "reason":  str,
      "answer":  str,
      "context": str   (only when return_context=True)
    }
    """
    # ── 0. Document-level summary shortcut (no retrieval, no extra LLM call) ──
    if _is_summary_query(question) and contract_id and route_override == "auto":
        store = get_artifact_store()
        summary = store.load_summary(contract_id)
        if summary:
            answer = format_summary_as_answer(summary)
            result: Dict = {
                "route":           "summary",
                "reason":          "Document-level summary query — returning pre-generated summary.",
                "rewritten_query": question,
                "answer":          answer,
            }
            if return_context:
                result["context"] = f"Pre-generated summary for contract: {contract_id}"
            return result

    # ── 1. Route ───────────────────────────────────────────────────────
    # Pass chat_history so the LLM router can resolve follow-up references.
    query_plan = route_question(question, chat_history=chat_history)

    route            = query_plan["route"]
    reason           = query_plan["reasoning"]
    rewritten_query  = query_plan["rewritten_query"]
    structural_scope = query_plan["structural_scope"]

    # Manual override from the UI or API caller
    if route_override and route_override != "auto":
        route = route_override
        reason = f"User override: {route_override}"

    # Downgrade graph/hybrid if the contract has no KG yet
    graph_available = contract_id in GRAPH_ENABLED_CONTRACTS
    if route in {"graph", "hybrid"} and not graph_available:
        route = "search"
        reason = (
            "Graph is not available for this contract yet — "
            "falling back to Azure AI Search."
        )

    # ── 2. Retrieve ────────────────────────────────────────────────────
    # Use rewritten_query for retrieval so pronouns/references are resolved.
    if route == "graph":
        context = graph_native_retrieve(rewritten_query)

    elif route == "tree":
        context = _tree_retrieve(
            question=rewritten_query,
            contract_id=contract_id,
            top=top,
        )

    elif route == "search":
        context = _search_retrieve(
            question=rewritten_query,
            contract_id=contract_id,
            top=top,
            structural_scope=structural_scope,
        )

    else:   # hybrid
        context = graph_rag_retrieve(
            question=rewritten_query,
            k=top,
            contract_id=contract_id,
            graph_ready_only=True,
        )

    # ── 3. Generate ────────────────────────────────────────────────────
    generator = AnswerGenerator()
    answer = generator.generate(
        question=question,          # original question for the LLM answer
        context=context,
        route=route,
        chat_history=chat_history or [],
    )

    result: Dict = {
        "route":           route,
        "reason":          reason,
        "rewritten_query": rewritten_query,
        "answer":          answer,
    }
    if return_context:
        result["context"] = context

    return result
