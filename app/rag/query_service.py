"""
Query service for Contract360.

Three retrieval routes:
  tree   — Azure AI Search (BM25+vector) + hierarchical tree context expansion.
  graph  — Cosmos Gremlin semantic graph only.
  hybrid — Tree search context + Gremlin semantic graph facts merged.

Returns citations[] alongside the answer so the frontend can render source cards.
"""

from typing import Dict, List, Optional, Tuple

from app.indexing.search_tester import AzureSearchTester
from app.rag.query_router import route_question
from app.rag.graph_retriever import graph_native_retrieve
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


# ── Citation extraction ────────────────────────────────────────────────────────

def _docs_to_citations(docs: list, route: str = "tree") -> List[Dict]:
    """Convert raw search/tree docs to structured citation objects."""
    citations = []
    seen = set()
    for doc in docs:
        cid   = doc.get("contractId") or ""
        title = doc.get("title") or doc.get("sectionTitle") or ""
        page_start = doc.get("pageStart") or ""
        page_end   = doc.get("pageEnd") or ""
        key = f"{cid}|{title}|{page_start}"
        if key in seen:
            continue
        seen.add(key)
        citations.append({
            "id":            doc.get("kgId") or doc.get("nodeId") or key,
            "contractId":    cid,
            "contractName":  cid.replace("_", " "),
            "clauseTitle":   title,
            "sectionTitle":  doc.get("sectionTitle") or "",
            "pageRange":     f"{page_start}–{page_end}" if page_start else "",
            "sourcePath":    doc.get("sourcePath") or "",
            "evidenceQuote": (doc.get("text") or "")[:200],
            "route":         route,
            "score":         round(doc.get("score", 0), 4),
        })
    return citations


def _chunks_to_citations(chunks: list) -> List[Dict]:
    """Convert SemanticRetriever chunk objects to citations."""
    citations = []
    seen = set()
    for chunk in chunks:
        cid   = chunk.get("contractId") or ""
        title = chunk.get("title") or chunk.get("sectionTitle") or ""
        page_start = chunk.get("pageStart") or ""
        page_end   = chunk.get("pageEnd") or ""
        key = f"{cid}|{title}|{page_start}"
        if key in seen:
            continue
        seen.add(key)
        citations.append({
            "id":            chunk.get("kgId") or chunk.get("nodeId") or key,
            "contractId":    cid,
            "contractName":  cid.replace("_", " "),
            "clauseTitle":   title,
            "sectionTitle":  chunk.get("sectionTitle") or "",
            "pageRange":     f"{page_start}–{page_end}" if page_start else "",
            "sourcePath":    chunk.get("sourcePath") or "",
            "evidenceQuote": (chunk.get("text") or "")[:200],
            "route":         "tree",
            "score":         round(chunk.get("score", 0), 4),
        })
    return citations


# ── Retrieval helpers — return (context_str, citations) ───────────────────────

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
) -> Tuple[str, List[Dict]]:
    """Returns (context_string, citations)."""
    if structural_scope:
        searcher = AzureSearchTester()
        docs = searcher.retrieve_structural_scope(
            structure_type=structural_scope["type"],
            identifier=structural_scope["identifier"],
            contract_id=contract_id,
            contract_ids=contract_ids,
            top=100,
        )
        return _format_search_docs(docs), _docs_to_citations(docs)

    # Normalise: treat empty list same as None (portfolio-wide)
    if contract_ids is not None and len(contract_ids) == 0:
        contract_ids = None

    if contract_id and not contract_ids:
        retriever = SemanticRetriever(contract_id=contract_id)
        chunks = retriever.retrieve(query=question, top_k=top, contract_id=contract_id)
        if chunks:
            context = build_rag_prompt(query=question, retrieved_chunks=chunks)
            return context, _chunks_to_citations(chunks)

    searcher = AzureSearchTester()
    docs = searcher.hybrid_search(
        query=question,
        contract_id=contract_id,
        contract_ids=contract_ids,
        top=top,
    )
    return _format_search_docs(docs), _docs_to_citations(docs)


def _hybrid_retrieve(
    question: str,
    contract_id: Optional[str],
    contract_ids: Optional[List[str]],
    top: int,
) -> Tuple[str, List[Dict]]:
    """Returns (context_string, citations). Merges tree + graph contexts."""
    tree_context, tree_citations = _tree_retrieve(
        question=question,
        contract_id=contract_id,
        contract_ids=contract_ids,
        top=top,
        structural_scope=None,
    )
    # Re-label tree citations as hybrid
    for c in tree_citations:
        c["route"] = "hybrid"

    graph_context = graph_native_retrieve(
        question=question,
        contract_id=contract_id,
        contract_ids=contract_ids,
    )

    # Append one graph citation per contract in scope
    scope_ids = contract_ids or ([contract_id] if contract_id else [])
    seen_ids = {c["contractId"] for c in tree_citations}
    graph_citations = [
        {
            "id":            cid,
            "contractId":    cid,
            "contractName":  cid.replace("_", " "),
            "clauseTitle":   "Knowledge Graph",
            "sectionTitle":  "",
            "pageRange":     "",
            "sourcePath":    "",
            "evidenceQuote": "",
            "route":         "graph",
            "score":         1.0,
        }
        for cid in scope_ids if cid not in seen_ids
    ]

    combined = (
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
    return combined, tree_citations + graph_citations


# ── Graph availability check ───────────────────────────────────────────────────

def _graph_available(contract_id: Optional[str], contract_ids: Optional[List[str]]) -> bool:
    if contract_ids and len(contract_ids) > 1:
        return gremlin_is_configured()
    if not contract_id and not contract_ids:
        return gremlin_is_configured()
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

    Returns {
      route, reason, rewritten_query, answer,
      citations: List[Dict],
      follow_up_suggestions: List[str],
      context?: str
    }
    """
    # Normalise empty list to None so all downstream checks work consistently
    if contract_ids is not None and len(contract_ids) == 0:
        contract_ids = None

    # ── 0. Document-level summary shortcut ────────────────────────────
    if _is_summary_query(question) and contract_id and route_override == "auto":
        store = get_artifact_store()
        summary = store.load_summary(contract_id)
        if summary:
            answer = format_summary_as_answer(summary)
            result: Dict = {
                "route":                "summary",
                "reason":               "Pre-generated document summary.",
                "rewritten_query":      question,
                "answer":               answer,
                "citations":            [],
                "follow_up_suggestions": [],
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

    graph_ok = _graph_available(contract_id, contract_ids)
    if route in {"graph", "hybrid"} and not graph_ok:
        route = "tree"
        reason = "No knowledge graph available for this contract — using tree search."

    # ── 2. Retrieve ────────────────────────────────────────────────────
    citations: List[Dict] = []

    if route == "graph":
        context = graph_native_retrieve(
            rewritten_query,
            contract_id=contract_id,
            contract_ids=contract_ids,
        )
        # Graph citations: derive from active contract scope (no chunk scores)
        scope_ids = contract_ids or ([contract_id] if contract_id else [])
        citations = [
            {
                "id":            cid,
                "contractId":    cid,
                "contractName":  cid.replace("_", " "),
                "clauseTitle":   "Knowledge Graph",
                "sectionTitle":  "",
                "pageRange":     "",
                "sourcePath":    "",
                "evidenceQuote": "",
                "route":         "graph",
                "score":         1.0,
            }
            for cid in scope_ids
        ]

    elif route == "hybrid":
        context, citations = _hybrid_retrieve(
            question=rewritten_query,
            contract_id=contract_id,
            contract_ids=contract_ids,
            top=top,
        )

    else:  # tree
        context, citations = _tree_retrieve(
            question=rewritten_query,
            contract_id=contract_id,
            contract_ids=contract_ids,
            top=top,
            structural_scope=structural_scope,
        )

    # ── 3. Generate answer + follow-up suggestions ─────────────────────
    active_ids: List[str] = []
    if contract_ids:
        active_ids = list(contract_ids)
    elif contract_id:
        active_ids = [contract_id]

    generator = AnswerGenerator()
    answer, follow_ups = generator.generate(
        question=question,
        context=context,
        route=route,
        chat_history=chat_history or [],
        active_contract_ids=active_ids or None,
    )

    result: Dict = {
        "route":                 route,
        "reason":                reason,
        "rewritten_query":       rewritten_query,
        "answer":                answer,
        "citations":             citations,
        "follow_up_suggestions": follow_ups,
    }
    if return_context:
        result["context"] = context

    return result
