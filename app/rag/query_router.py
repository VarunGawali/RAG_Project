"""
Simple query router for Contract360 demo.

Routes:
- graph: direct Cosmos Gremlin semantic KG queries
- search: Azure AI Search/tree RAG only
- hybrid: Azure AI Search + Cosmos Gremlin graph expansion
"""

from typing import Dict


def route_question(question: str) -> Dict:
    q = question.lower()

    evidence_terms = [
        "cite",
        "citation",
        "evidence",
        "source",
        "where stated",
        "supporting clause",
        "with support",
    ]

    graph_terms = [
        "obligation",
        "obligations",
        "owed",
        "owe",
        "responsible",
        "deadline",
        "due",
        "by when",
        "right",
        "rights",
        "restriction",
        "prohibit",
        "shall not",
        "who owes",
        "owed to",
    ]

    search_terms = [
        "summarize",
        "explain",
        "what does",
        "define",
        "definition",
        "article",
        "section",
        "clause",
        "meaning",
    ]

    hybrid_topic_terms = [
        "environmental",
        "nerc",
        "cip",
        "indemnification",
        "liability",
        "breach",
        "default",
        "termination",
        "remedies",
        "notice",
        "reporting",
        "community right to know",
    ]

    has_graph_term = any(t in q for t in graph_terms)
    has_evidence_term = any(t in q for t in evidence_terms)
    has_search_term = any(t in q for t in search_terms)
    has_hybrid_topic = any(t in q for t in hybrid_topic_terms)

    if has_graph_term and has_evidence_term:
        return {
            "route": "hybrid",
            "reason": "structured legal fact question with evidence/citation request",
        }

    if has_hybrid_topic and (has_search_term or has_graph_term):
        return {
            "route": "hybrid",
            "reason": "topic needs source text plus graph/legal context",
        }

    if has_graph_term:
        return {
            "route": "graph",
            "reason": "structured legal fact question",
        }

    if has_search_term:
        return {
            "route": "search",
            "reason": "text explanation or summarization question",
        }

    return {
        "route": "hybrid",
        "reason": "default route for mixed semantic/legal question",
    }


if __name__ == "__main__":
    questions = [
        "What obligations does Con Edison have?",
        "Which obligations have deadlines?",
        "If a Breach is not cured, what remedies does the non-Breaching Party have?",
        "Summarize Article XII.",
        "Summarize Con Edison’s environmental obligations with citations.",
    ]

    for q in questions:
        print(q)
        print(route_question(q))
        print()