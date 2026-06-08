"""
LLM-based query router for Contract360.

Replaces the original keyword-regex router with a single Azure OpenAI
classification call that outputs a structured QueryPlan.

QueryPlan fields
----------------
route           : "search" | "graph" | "hybrid" | "tree"
reasoning       : one-sentence explanation of the choice
rewritten_query : improved query for vector search (pronouns resolved,
                  context from chat history folded in)
structural_scope: {"type": "Article"|"Section"|"Clause",
                   "identifier": "XII"}  or null

Fallback
--------
If the LLM call fails for any reason (timeout, malformed JSON, etc.)
the function transparently falls back to the original keyword classifier
so the system never hard-errors on routing.
"""

import json
import logging
import re
from typing import Dict, List, Optional

from openai import AzureOpenAI

from app import config

logger = logging.getLogger(__name__)


# ── Routing system prompt ──────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a query router for a contract intelligence system.

Given a user question and optional conversation history, output a JSON query plan.

ROUTES
------
"search"  — text lookup, summarization, or structural navigation questions.
            Examples: "summarize Article XII", "what does section 5.2 say",
            "explain the indemnification clause", "what services are excluded?"

"graph"   — structured fact questions about obligations, rights, deadlines, or
            parties — questions whose answer lives as a graph fact.
            Examples: "what does Con Edison owe?", "which obligations have deadlines?",
            "who is responsible for NERC compliance?", "what are the payment obligations?"

"hybrid"  — questions that need BOTH source text evidence AND graph facts, or that
            ask for citations alongside structured facts.
            Examples: "what are Con Edison's environmental obligations with citations?",
            "what are the termination remedies and where are they stated?",
            "summarize Con Edison's obligations with supporting clauses"

"tree"    — questions that require understanding hierarchical document structure:
            how clauses relate to their parent sections, what sibling clauses say,
            or navigating the contract outline across multiple levels.
            Examples: "walk me through the payment structure",
            "how do the sub-clauses of Article V relate?",
            "what conditions flow from Section 3 into Section 4?"

OUTPUT FORMAT
-------------
Output ONLY valid JSON — no markdown fences, no extra text:
{
  "route": "search" | "graph" | "hybrid" | "tree",
  "reasoning": "<one sentence>",
  "rewritten_query": "<improved query for vector search — resolve pronouns and
                       references using chat history, add domain context>",
  "structural_scope": {"type": "Article"|"Section"|"Clause", "identifier": "<value>"} | null
}

For rewritten_query: if the user says "what about the other party?" after a question
about Con Edison, rewrite to "What obligations does the Power Authority have?"
For structural_scope: only set when the user explicitly names an Article, Section,
or Clause (e.g. "Article XII" → {"type": "Article", "identifier": "XII"}).
"""


# ── Public entry point ─────────────────────────────────────────────────────────

def route_question(
    question: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> Dict:
    """
    Classify a question and return a QueryPlan dict.

    Parameters
    ----------
    question     : current user question
    chat_history : prior turns as [{"role": "user"|"assistant", "content": "..."}]
                   used to resolve follow-up references in rewritten_query

    Returns
    -------
    {
      "route":           str,
      "reasoning":       str,
      "rewritten_query": str,
      "structural_scope": dict | None,
    }
    """
    try:
        return _llm_route(question, chat_history or [])
    except Exception as exc:
        logger.warning(
            "LLM router failed (%s: %s) — falling back to keyword classifier.",
            type(exc).__name__, exc,
        )
        return _keyword_route(question)


# ── LLM classifier ─────────────────────────────────────────────────────────────

def _llm_route(
    question: str,
    chat_history: List[Dict[str, str]],
) -> Dict:
    client = AzureOpenAI(
        azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
        api_key=config.AZURE_OPENAI_API_KEY,
        api_version=config.AZURE_OPENAI_API_VERSION,
    )

    # Build the messages array.
    # Include the last 4 turns (2 user + 2 assistant) as context so the
    # router can resolve references like "it", "that clause", "the other party".
    tail = chat_history[-(4 * 2):]  # last 4 turns = up to 8 messages

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
    logger.info(
        "LLM router → route=%s  reason=%s",
        plan["route"], plan["reasoning"],
    )
    return plan


def _parse_plan(raw: str, original_question: str) -> Dict:
    """Parse LLM JSON output; fall back to keyword classifier on bad JSON."""
    # Strip accidental markdown fences
    cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Router returned non-JSON: %r — using fallback.", raw[:120])
        return _keyword_route(original_question)

    route = data.get("route", "").lower()
    if route not in {"search", "graph", "hybrid", "tree"}:
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


# ── Keyword fallback ───────────────────────────────────────────────────────────

def _keyword_route(question: str) -> Dict:
    """
    Original keyword-based classifier kept as a reliable fallback.
    Returns the same QueryPlan shape as the LLM classifier.
    """
    q = question.lower()

    graph_terms = [
        "obligation", "obligations", "owed", "owe", "responsible",
        "deadline", "due", "by when", "right", "rights", "restriction",
        "prohibit", "shall not", "who owes", "owed to",
    ]
    evidence_terms = [
        "cite", "citation", "evidence", "source", "where stated",
        "supporting clause", "with support",
    ]
    search_terms = [
        "summarize", "explain", "what does", "define", "definition",
        "article", "section", "clause", "meaning",
    ]
    hybrid_topics = [
        "environmental", "nerc", "cip", "indemnification", "liability",
        "breach", "default", "termination", "remedies", "notice",
        "reporting", "community right to know",
    ]

    has_graph    = any(t in q for t in graph_terms)
    has_evidence = any(t in q for t in evidence_terms)
    has_search   = any(t in q for t in search_terms)
    has_hybrid   = any(t in q for t in hybrid_topics)

    if has_graph and has_evidence:
        route, reason = "hybrid", "obligation question with evidence/citation request"
    elif has_hybrid and (has_search or has_graph):
        route, reason = "hybrid", "topic needs source text plus graph/legal context"
    elif has_graph:
        route, reason = "graph", "structured legal fact question"
    elif has_search:
        route, reason = "search", "text explanation or summarization question"
    else:
        route, reason = "hybrid", "default route for mixed semantic/legal question"

    return {
        "route":            route,
        "reasoning":        reason,
        "rewritten_query":  question,
        "structural_scope": _extract_structural_scope(question),
    }


def _extract_structural_scope(question: str) -> Optional[Dict]:
    """Extract Article/Section/Clause reference from question text."""
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