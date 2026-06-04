"""
Query service for Streamlit and CLI.

Routes a question to:
- graph route
- search route
- hybrid route

For demo:
- Edison contract supports graph/hybrid.
- Newly uploaded contracts support search-only unless graph is later built.
"""

import re
from typing import Dict, Optional

from app.indexing.search_tester import AzureSearchTester
from app.rag.query_router import route_question
from app.rag.graph_retriever import graph_native_retrieve
from app.rag.hybrid_retriever import graph_rag_retrieve
from app.rag.answer_generator import AnswerGenerator


GRAPH_ENABLED_CONTRACTS = {
    "Edison_NYPA_OandM_Contract_1",
}


ROMAN_MAP = {
    "1": "I",
    "2": "II",
    "3": "III",
    "4": "IV",
    "5": "V",
    "6": "VI",
    "7": "VII",
    "8": "VIII",
    "9": "IX",
    "10": "X",
    "11": "XI",
    "12": "XII",
    "13": "XIII",
    "14": "XIV",
    "15": "XV",
    "16": "XVI",
    "17": "XVII",
    "18": "XVIII",
    "19": "XIX",
    "20": "XX",
    "21": "XXI",
    "22": "XXII",
    "23": "XXIII",
    "24": "XXIV",
    "25": "XXV",
    "26": "XXVI",
    "27": "XXVII",
    "28": "XXVIII",
    "29": "XXIX",
    "30": "XXX",
    "31": "XXXI",
    "32": "XXXII",
    "33": "XXXIII",
    "34": "XXXIV",
}


def extract_structural_scope(question: str):
    """
    Detect structural scope like Article XII / Article 12.
    Later this can be replaced by LLM QueryPlan.
    """

    article_match = re.search(
        r"\barticle\s+([ivxlcdm]+|\d+)\b",
        question,
        re.IGNORECASE,
    )

    if article_match:
        value = article_match.group(1).upper()

        if value.isdigit():
            value = ROMAN_MAP.get(value, value)

        return {
            "structure_type": "Article",
            "identifier": value,
        }

    section_match = re.search(
        r"\bsection\s+([0-9]+(?:\.[0-9]+)*)\b",
        question,
        re.IGNORECASE,
    )

    if section_match:
        return {
            "structure_type": "Section",
            "identifier": section_match.group(1),
        }

    clause_match = re.search(
        r"\bclause\s+([0-9]+(?:\.[0-9]+)*)\b",
        question,
        re.IGNORECASE,
    )

    if clause_match:
        return {
            "structure_type": "Clause",
            "identifier": clause_match.group(1),
        }

    return None


def format_search_docs(docs):
    if not docs:
        return "No Azure AI Search results found."

    parts = []

    for idx, doc in enumerate(docs, start=1):
        parts.append("=" * 80)
        parts.append(f"SEARCH RESULT {idx}")
        parts.append("=" * 80)
        parts.append(f"Title: {doc.get('title')}")
        parts.append(f"Section: {doc.get('sectionTitle')}")
        parts.append(f"Pages: {doc.get('pageStart')}-{doc.get('pageEnd')}")
        parts.append(f"Source path: {doc.get('sourcePath')}")
        parts.append(f"kgId: {doc.get('kgId')}")
        parts.append("")
        parts.append(doc.get("text") or "")
        parts.append("")

    return "\n".join(parts)


def search_only_retrieve(
    question: str,
    contract_id: Optional[str],
    top: int = 5,
) -> str:
    searcher = AzureSearchTester()

    scope = extract_structural_scope(question)

    if scope:
        docs = searcher.retrieve_structural_scope(
            structure_type=scope["structure_type"],
            identifier=scope["identifier"],
            contract_id=contract_id,
            top=100,
        )

        return format_search_docs(docs)

    docs = searcher.hybrid_search(
        query=question,
        contract_id=contract_id,
        top=top,
    )

    return format_search_docs(docs)


def answer_question(
    question: str,
    contract_id: Optional[str],
    top: int = 4,
    route_override: str = "auto",
    return_context: bool = False,
) -> Dict:
    """
    Main query service.

    Returns:
    {
      "route": "...",
      "reason": "...",
      "context": "...",
      "answer": "..."
    }
    """

    routing = route_question(question)
    route = routing["route"]
    reason = routing["reason"]

    if route_override and route_override != "auto":
        route = route_override
        reason = f"User override: {route_override}"

    graph_available = contract_id in GRAPH_ENABLED_CONTRACTS

    if route in ["graph", "hybrid"] and not graph_available:
        route = "search"
        reason = (
            "Graph is not available for this contract yet. "
            "Falling back to Azure AI Search route."
        )

    if route == "graph":
        context = graph_native_retrieve(question)

    elif route == "search":
        context = search_only_retrieve(
            question=question,
            contract_id=contract_id,
            top=top,
        )

    else:
        context = graph_rag_retrieve(
            question=question,
            k=top,
            contract_id=contract_id,
            graph_ready_only=True,
        )

    generator = AnswerGenerator()

    answer = generator.generate(
        question=question,
        context=context,
        route=route,
    )

    result = {
        "route": route,
        "reason": reason,
        "answer": answer,
    }

    if return_context:
        result["context"] = context

    return result