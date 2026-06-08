"""
Query service for Contract360.

Three retrieval routes:
  tree   — Azure AI Search (BM25+vector) + hierarchical tree context expansion.
           Handles text lookup, summarization, structural navigation.
  graph  — Cosmos Gremlin semantic graph only.
           Handles obligations, rights, deadlines, party relationships.
           Supports single-contract, multi-contract, and cross-contract queries.
  hybrid — Tree search context + Gremlin semantic graph facts merged.
           Best for questions needing both clause text evidence and structured facts.

Routing: LLM classifier (query_router.py) with keyword fallback.
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
from app.kg.gremlin_writer import contract_has_graph, gremlin_is_configured


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
            f"SEARCH RESULT {idx}  [CONTRACT: {doc.get('contractId', 'unknown')}]",
            "=" * 80,
            f"Contract ID: {doc.get('contractId')}",
            f"Title: {doc.get('title')}",
            f"Section: {doc.get('sectionTitle')}",
            f"Pages: {doc.get('pageStart')}-{doc.get('pageEnd')}",
            f"Source path: {doc.get('sourcePath')}",
            "",
            doc.get("text") or "",
            "",
        ]
    return "\n".join(parts)


def _tree_retrieve(
    question: str,
    contract_id: Optional[str],
    contract_ids: Optional[List[str]],
    top: int,
    structural_scope: Optional[Dict],
) -> str:
    """
    Azure AI Search (BM25+vector) + hierarchical tree context expansion.

    For structural scope questions (Article/Section/Clause references), uses
    the structural index path. Otherwise uses SemanticRetriever for tree context
    when a single contract is active, or flat hybrid search for multi-contract.
    """
    # Structural scope: always use the search index (exact article/section lookup)
    if structural_scope:
        searcher = AzureSearchTester()
        docs = searcher.retrieve_structural_scope(
            structure_type=structural_scope["type"],
            identifier=structural_scope["identifier"],
            contract_id=contract_id,
            contract_ids=contract_ids,
            top=100,
        )
        return _format_search_docs(docs)

    # Single contract with tree artifacts: use SemanticRetriever for rich expansion
    if contract_id and not contract_ids:
        retriever = SemanticRetriever(contract_id=contract_id)
        chunks = retriever.retrieve(query=question, top_k=top, contract_id=contract_id)
        if chunks:
            return build_rag_prompt(query=question, retrieved_chunks=chunks)

    # Multi-contract or fallback: hybrid BM25+vector search, labelled by contract
    searcher = AzureSearchTester()
    docs = searcher.hybrid_search(
        query=question,
        contract_id=contract_id,
        contract_ids=contract_ids,
        top=top,
    )
    return _format_search_docs(docs)


def _hybrid_retrieve(
    question: str,
    contract_id: Optional[str],
    contract_ids: Optional[List[str]],
    top: int,
) -> str:
    """
    Tree search context (Azure AI Search) merged with Gremlin semantic graph facts.
    Gives the LLM both clause text evidence and structured obligation/party data.
    """
    # Tree side
    tree_context = _tree_retrieve(
        question=question,
        contract_id=contract_id,
        contract_ids=contract_ids,
        top=top,
        structural_scope=None,
    )

    # Graph side — use contract-scoped graph retrieval
    graph_context = graph_native_retrieve(
        question=question,
        contract_id=contract_id,
        contract_ids=contract_ids,
    )

    return (
        "=" * 80 + "\n"
        "TREE SEARCH CONTEXT (Azure AI Search + Hierarchical Expansion)\n"
        + "=" * 80 + "\n"
        + tree_context
        + "\n\n"
        + "=" * 80 + "\n"
        "GRAPH CONTEXT (Cosmos Gremlin Semantic Facts)\n"
        + "=" * 80 + "\n"
        + graph_context
    )


# ── Graph availability check ───────────────────────────────────────────────────

def _graph_available(contract_id: Optional[str], contract_ids: Optional[List[str]]) -> bool:
    """
    Return True if KG data exists for the active scope.
    For multi-contract or portfolio queries, True if Gremlin is configured at all.
    """
    if contract_ids and len(contract_ids) > 1:
        # Multi-contract: if Gremlin is configured it has the 9 pre-existing contracts
        return gremlin_is_configured()
    if not contract_id and not contract_ids:
        # Portfolio-wide: same
        return gremlin_is_configured()
    # Single contract check
    cid = contract_id or (contract_ids[0] if contract_ids else None)
    if not cid:
        return False
    if gremlin_is_configured():
        return contract_has_graph(cid)
    _store = get_artifact_store()
    return _store.kg_exists(cid)


# ── Main entry point ───────────────────────────────────────────────────────────

def answer_question(
    question: str,
    contract_id: Optional[str],
    contract_ids: Optional[List[str]] = None,
    top: int = 4,
    route_override: str = "auto",
    return_context: bool = False,
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> Dict:
    """
    Route, retrieve, and answer a question.

    Returns { route, reason, rewritten_query, answer, context? }
    """
    # ── 0. Document-level summary shortcut ────────────────────────────
    if _is_summary_query(question) and contract_id and route_override == "auto":
        store = get_artifact_store()
        summary = store.load_summary(contract_id)
        if summary:
            answer = format_summary_as_answer(summary)
            result: Dict = {
                "route":           "summary",
                "reason":          "Pre-generated document summary.",
                "rewritten_query": question,
                "answer":          answer,
            }
            if return_context:
                result["context"] = f"Pre-generated summary for: {contract_id}"
            return result

    # ── 1. Route ──────────────────────────────────────────────────────
    query_plan = route_question(question, chat_history=chat_history)
    route            = query_plan["route"]
    reason           = query_plan["reasoning"]
    rewritten_query  = query_plan["rewritten_query"]
    structural_scope = query_plan["structural_scope"]

    if route_override and route_override != "auto":
        route = route_override
        reason = f"User override: {route_override}"

    # Downgrade graph/hybrid to tree if no KG exists for this scope
    graph_ok = _graph_available(contract_id, contract_ids)
    if route in {"graph", "hybrid"} and not graph_ok:
        route = "tree"
        reason = "No knowledge graph available for this contract — using tree search."

    # ── 2. Retrieve ────────────────────────────────────────────────────
    if route == "graph":
        context = graph_native_retrieve(
            rewritten_query,
            contract_id=contract_id,
            contract_ids=contract_ids,
        )

    elif route == "hybrid":
        context = _hybrid_retrieve(
            question=rewritten_query,
            contract_id=contract_id,
            contract_ids=contract_ids,
            top=top,
        )

    else:  # tree (default for all text/structural questions)
        context = _tree_retrieve(
            question=rewritten_query,
            contract_id=contract_id,
            contract_ids=contract_ids,
            top=top,
            structural_scope=structural_scope,
        )

    # ── 3. Generate ────────────────────────────────────────────────────
    active_ids: List[str] = []
    if contract_ids:
        active_ids = list(contract_ids)
    elif contract_id:
        active_ids = [contract_id]

    generator = AnswerGenerator()
    answer = generator.generate(
        question=question,
        context=context,
        route=route,
        chat_history=chat_history or [],
        active_contract_ids=active_ids or None,
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
