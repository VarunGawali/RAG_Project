"""
Query service for Contract360.

Three retrieval routes:
  tree   — Azure AI Search (BM25+vector) + hierarchical tree context expansion.
  graph  — Cosmos Gremlin semantic graph only.
  hybrid — Tree search context + Gremlin semantic graph facts merged.

Returns citations[] alongside the answer so the frontend can render source cards.
"""

import logging
import re as _re
from typing import Dict, List, Optional, Tuple

from app.indexing.search_tester import AzureSearchTester
from app.rag.contract_resolver import resolve_scope
from app.rag.query_router import route_question
from app.rag.graph_retriever import graph_native_retrieve
from app.rag.graph_canonical import canonical_graph_retrieve
from app.rag.answer_generator import AnswerGenerator
from app.rag.summary_generator import format_summary_as_answer
from app.services.prompt_builder import build_rag_prompt
from app.storage.artifact_store import get_artifact_store
from app.tree.semantic_retriever import SemanticRetriever
from app.kg.gremlin_writer import contract_has_graph, gremlin_is_configured

logger = logging.getLogger(__name__)


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

    graph_context, graph_facts = _graph_retrieve(
        question=question,
        contract_id=contract_id,
        contract_ids=contract_ids,
    )

    # Prefer fact-level graph citations; fall back to scope cards if none.
    graph_citations = _graph_facts_to_citations(graph_facts)
    if not graph_citations:
        scope_ids = contract_ids or ([contract_id] if contract_id else [])
        seen_ids = {c["contractId"] for c in tree_citations}
        graph_citations = [
            {
                "id": cid, "contractId": cid, "contractName": cid.replace("_", " "),
                "clauseTitle": "Knowledge Graph", "sectionTitle": "", "pageRange": "",
                "sourcePath": "", "evidenceQuote": "", "route": "graph", "score": 1.0,
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

def _make_search_anchor():
    """Phase-2 bridge: vector/keyword search → relevant clause ids for graph anchoring."""
    def _anchor(question: str, scope: Optional[List[str]]) -> List[str]:
        try:
            searcher = AzureSearchTester()
            docs = searcher.hybrid_search(query=question, contract_ids=scope, top=8)
            return [d.get("kgId") for d in docs if d.get("kgId")]
        except Exception:
            return []
    return _anchor


_MAX_GRAPH_CITATIONS = 25


def _graph_facts_to_citations(facts: List[Dict]) -> List[Dict]:
    """Build citation cards from graph facts (with page/clause provenance)."""
    citations, seen = [], set()
    for f in facts:
        cid = f.get("contractId") or ""
        title = f.get("clauseTitle") or f.get("name") or ""
        ps, pe = f.get("pageStart"), f.get("pageEnd")
        key = f"{cid}|{title}|{ps}"
        if key in seen:
            continue
        seen.add(key)
        citations.append({
            "id":            f.get("kgId") or key,
            "contractId":    cid,
            "contractName":  cid.replace("_", " "),
            "clauseTitle":   title,
            "sectionTitle":  "",
            "pageRange":     f"{ps}–{pe}" if ps else "",
            "sourcePath":    "",
            "evidenceQuote": (f.get("evidenceQuote") or "")[:200],
            "route":         "graph",
            "score":         float(f.get("confidence") or 0.0),
        })
        if len(citations) >= _MAX_GRAPH_CITATIONS:
            break
    return citations


def _ground_and_generate(
    generator,
    question: str,
    context: str,
    route: str,
    citations: List[Dict],
    chat_history: List[Dict[str, str]],
    active_ids: Optional[List[str]],
):
    """
    Rank citations, expose them to the LLM as a numbered SOURCES list, let it
    cite [S#] inline, then return only the cited cards. Falls back to top-ranked
    few if the model cites nothing. Strips [S#] markers from the displayed answer.
    """
    ranked = sorted(citations, key=lambda c: c.get("score", 0.0), reverse=True)

    if ranked:
        lines = ["", "", "=" * 70, "SOURCES (cite the supporting one inline as [S#]):", "=" * 70]
        for i, c in enumerate(ranked, 1):
            pg = f" ({c['pageRange']})" if c.get("pageRange") else ""
            lines.append(f"[S{i}] {c.get('clauseTitle') or c.get('contractName')}"
                         f" — {c.get('contractName')}{pg}")
        context = context + "\n".join(lines)

    answer, follow_ups = generator.generate(
        question=question, context=context, route=route,
        chat_history=chat_history, active_contract_ids=active_ids,
    )

    used = [int(n) for n in _re.findall(r"\[S(\d+)\]", answer)]
    seen_set, order = set(), []
    for n in used:
        if 1 <= n <= len(ranked) and n not in seen_set:
            seen_set.add(n)
            order.append(n)

    grounded = [ranked[n - 1] for n in order] if order else ranked[:8]
    clean = _re.sub(r"\s*\[S\d+\]", "", answer)
    return clean, follow_ups, grounded


def _graph_retrieve(question: str, contract_id: Optional[str],
                    contract_ids: Optional[List[str]]):
    """Smart canonical-anchored graph retrieval, falling back to legacy template retriever."""
    ctx, facts = canonical_graph_retrieve(
        question, contract_id=contract_id, contract_ids=contract_ids,
        search_anchor_fn=_make_search_anchor(),
    )
    if ctx and ctx.strip():
        return ctx, _graph_facts_to_citations(facts)
    legacy = graph_native_retrieve(question, contract_id=contract_id, contract_ids=contract_ids)
    return legacy, []

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

    # ── Scope resolution: narrow to contracts the question names ──────
    scope_reason: Optional[str] = None
    if contract_ids:
        candidate_pool = list(contract_ids)
    elif contract_id:
        candidate_pool = [contract_id]
    else:
        try:
            candidate_pool = AzureSearchTester().list_contract_ids()
        except Exception as exc:
            logger.warning("Contract resolver: could not list contracts (%s).", exc)
            candidate_pool = []

    resolved_ids, scope_reason = resolve_scope(question, candidate_pool)
    if scope_reason:
        contract_ids = resolved_ids
        contract_id = None

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

    if scope_reason:
        reason = f"{reason} ({scope_reason})"

    # ── 2. Retrieve ────────────────────────────────────────────────────
    citations: List[Dict] = []

    if route == "graph":
        context, citations = _graph_retrieve(
            rewritten_query,
            contract_id=contract_id,
            contract_ids=contract_ids,
        )
        if not citations:
            scope_ids = contract_ids or ([contract_id] if contract_id else [])
            citations = [
                {
                    "id": cid, "contractId": cid, "contractName": cid.replace("_", " "),
                    "clauseTitle": "Knowledge Graph", "sectionTitle": "", "pageRange": "",
                    "sourcePath": "", "evidenceQuote": "", "route": "graph", "score": 1.0,
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
    answer, follow_ups, citations = _ground_and_generate(
        generator,
        question=question,
        context=context,
        route=route,
        citations=citations,
        chat_history=chat_history or [],
        active_ids=active_ids or None,
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
