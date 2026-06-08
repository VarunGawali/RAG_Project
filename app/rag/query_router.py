"""
LLM-based query router for Contract360.

Three routes:
  tree   — Azure AI Search + hierarchical tree context expansion.
           Use for text lookup, summarization, and structural navigation.
  graph  — Cosmos Gremlin semantic graph only.
           Use for obligations, rights, deadlines, party relationships.
  hybrid — Both tree search AND graph facts merged.
           Use when the question needs clause text evidence AND structured facts.

Fallback: keyword classifier if the LLM call fails.
"""

import json
import logging
import re
from typing import Dict, List, Optional

from openai import AzureOpenAI

from app import config

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """You are a query router for a contract intelligence system.

Given a user question and optional conversation history, output a JSON query plan.

ROUTES
------
"tree"   — text lookup, summarization, or structural navigation questions.
           The system will use Azure AI Search to find relevant clauses and
           then expand context hierarchically through the document tree.
           Examples:
             "summarize Article XII"
             "what does section 5.2 say?"
             "explain the indemnification clause"
             "what services are excluded?"
             "walk me through the payment structure"
             "what does this contract say about force majeure?"

"graph"  — structured fact questions whose answer is a relationship or entity
           in the knowledge graph: obligations, rights, deadlines, parties.
           Examples:
             "what does Con Edison owe?"
             "which obligations have deadlines?"
             "who is responsible for NERC compliance?"
             "what rights does the Power Authority have?"
             "compare payment obligations across contracts"
             "which parties appear in multiple contracts?"

"hybrid" — questions that need BOTH source clause text AND structured graph facts,
           or that explicitly ask for citations alongside structured facts.
           Examples:
             "what are Con Edison's environmental obligations with citations?"
             "what are the termination remedies and where are they stated?"
             "summarize obligations with supporting clause references"
             "what does the contract say about indemnification and what are the parties' obligations?"

OUTPUT FORMAT
-------------
Output ONLY valid JSON — no markdown fences, no extra text:
{
  "route": "tree" | "graph" | "hybrid",
  "reasoning": "<one sentence>",
  "rewritten_query": "<improved query — resolve pronouns using chat history, add domain context>",
  "structural_scope": {"type": "Article"|"Section"|"Clause", "identifier": "<value>"} | null
}

For rewritten_query: if the user says "what about the other party?" after a question
about Con Edison, rewrite to "What obligations does the Power Authority have?"
For structural_scope: only set when the user explicitly names an Article, Section,
or Clause (e.g. "Article XII" → {"type": "Article", "identifier": "XII"}).
"""


def route_question(
    question: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> Dict:
    try:
        return _llm_route(question, chat_history or [])
    except Exception as exc:
        logger.warning(
            "LLM router failed (%s: %s) — falling back to keyword classifier.",
            type(exc).__name__, exc,
        )
        return _keyword_route(question)


def _llm_route(question: str, chat_history: List[Dict[str, str]]) -> Dict:
    client = AzureOpenAI(
        azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
        api_key=config.AZURE_OPENAI_API_KEY,
        api_version=config.AZURE_OPENAI_API_VERSION,
    )

    tail = chat_history[-(4 * 2):]
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    messages.extend(tail)
    messages.append({"role": "user", "content": question})

    response = client.chat.completions.create(
        model=config.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=messages,
        temperature=0,
        max_tokens=200,
    )

    raw = response.choices[0].message.content or ""
    plan = _parse_plan(raw, question)
    logger.info("LLM router → route=%s  reason=%s", plan["route"], plan["reasoning"])
    return plan


def _parse_plan(raw: str, original_question: str) -> Dict:
    cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Router returned non-JSON: %r — using fallback.", raw[:120])
        return _keyword_route(original_question)

    route = data.get("route", "").lower()
    if route not in {"tree", "graph", "hybrid"}:
        # map legacy "search" to "tree" gracefully
        if route == "search":
            route = "tree"
        else:
            logger.warning("Router returned unknown route %r — using fallback.", route)
            return _keyword_route(original_question)

    structural_scope = data.get("structural_scope")
    if structural_scope and not isinstance(structural_scope, dict):
        structural_scope = None

    return {
        "route":            route,
        "reasoning":        data.get("reasoning", "LLM classification"),
        "rewritten_query":  data.get("rewritten_query") or original_question,
        "structural_scope": structural_scope,
    }


def _keyword_route(question: str) -> Dict:
    q = question.lower()

    graph_terms = [
        "obligation", "obligations", "owed", "owe", "responsible",
        "deadline", "due", "by when", "right", "rights", "restriction",
        "prohibit", "shall not", "who owes", "owed to",
        "compare", "across contracts", "shared parties", "portfolio",
    ]
    evidence_terms = [
        "cite", "citation", "evidence", "source", "where stated",
        "supporting clause", "with support",
    ]
    text_terms = [
        "summarize", "explain", "what does", "define", "definition",
        "article", "section", "clause", "meaning", "walk me through",
        "what is", "describe",
    ]
    hybrid_topics = [
        "environmental", "nerc", "cip", "indemnification", "liability",
        "breach", "default", "termination", "remedies", "notice",
        "reporting", "community right to know",
    ]

    has_graph    = any(t in q for t in graph_terms)
    has_evidence = any(t in q for t in evidence_terms)
    has_text     = any(t in q for t in text_terms)
    has_hybrid   = any(t in q for t in hybrid_topics)

    if has_graph and (has_evidence or has_hybrid):
        route, reason = "hybrid", "structured facts requested with evidence/citations"
    elif has_graph:
        route, reason = "graph", "structured legal fact question"
    elif has_text:
        route, reason = "tree", "text explanation or structural navigation"
    elif has_hybrid:
        route, reason = "hybrid", "complex topic needing clause text and graph context"
    else:
        route, reason = "hybrid", "default: combined tree + graph for best coverage"

    return {
        "route":            route,
        "reasoning":        reason,
        "rewritten_query":  question,
        "structural_scope": _extract_structural_scope(question),
    }


def _extract_structural_scope(question: str) -> Optional[Dict]:
    _ROMAN_MAP = {
        str(i): roman for i, roman in enumerate(
            ["I","II","III","IV","V","VI","VII","VIII","IX","X",
             "XI","XII","XIII","XIV","XV","XVI","XVII","XVIII","XIX","XX",
             "XXI","XXII","XXIII","XXIV","XXV","XXVI","XXVII","XXVIII","XXIX","XXX",
             "XXXI","XXXII","XXXIII","XXXIV"], start=1
        )
    }
    m = re.search(r"\barticle\s+([ivxlcdm]+|\d+)\b", question, re.IGNORECASE)
    if m:
        val = m.group(1).upper()
        return {"type": "Article", "identifier": _ROMAN_MAP.get(val, val)}
    m = re.search(r"\bsection\s+([0-9]+(?:\.[0-9]+)*)\b", question, re.IGNORECASE)
    if m:
        return {"type": "Section", "identifier": m.group(1)}
    m = re.search(r"\bclause\s+([0-9]+(?:\.[0-9]+)*)\b", question, re.IGNORECASE)
    if m:
        return {"type": "Clause", "identifier": m.group(1)}
    return None
