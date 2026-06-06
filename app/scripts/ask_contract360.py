"""
Demo Contract360 GraphRAG CLI.

Examples:

Final answer only:
python -m app.scripts.ask_contract360 "What obligations does Con Edison have?"

Debug retrieval only:
python -m app.scripts.ask_contract360 "What obligations does Con Edison have?" --no-llm

Show retrieval context plus final answer:
python -m app.scripts.ask_contract360 "Summarize Article XII." --show-context
"""

import argparse
import re

from app.rag.query_router import route_question
from app.rag.graph_retriever import graph_native_retrieve
from app.rag.hybrid_retriever import graph_rag_retrieve
from app.rag.answer_generator import AnswerGenerator
from app.indexing.search_tester import AzureSearchTester


DEFAULT_CONTRACT_ID = "Edison_NYPA_OandM_Contract_1"


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
    Detect structural scope from natural language.

    Examples:
    - "Summarize Article XII"
      -> {"structure_type": "Article", "identifier": "XII"}

    - "Summarize Article 12"
      -> {"structure_type": "Article", "identifier": "XII"}

    This is generic enough for demo and can later be replaced by an LLM QueryPlan.
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
    """
    Format Azure AI Search documents into retrieval context.
    """

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
    contract_id: str = DEFAULT_CONTRACT_ID,
    top: int = 20,
) -> str:
    """
    Search-only retrieval.

    If the question refers to a structural scope like Article XII,
    retrieve all docs under that scope using filters rather than vector search.

    Otherwise use normal hybrid/vector search.
    """

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


def retrieve_context(question: str, route: str, contract_id: str, top: int) -> str:
    """
    Retrieve context according to selected route.
    """

    if route == "graph":
        return graph_native_retrieve(question)

    if route == "search":
        return search_only_retrieve(
            question=question,
            contract_id=contract_id,
            top=top,
        )

    return graph_rag_retrieve(
        question=question,
        k=top,
        contract_id=contract_id,
        graph_ready_only=True,
    )


def main():
    parser = argparse.ArgumentParser("ask-contract360")

    parser.add_argument("question")
    parser.add_argument("--contract-id", default=DEFAULT_CONTRACT_ID)
    parser.add_argument("--top", type=int, default=4)

    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Print retrieval context only without LLM answer generation.",
    )

    parser.add_argument(
        "--show-context",
        action="store_true",
        help="Print retrieval context before final answer.",
    )

    args = parser.parse_args()

    routing = route_question(args.question)
    route = routing["route"]

    print("\n" + "=" * 100)
    print("CONTRACT360 GRAPHRAG DEMO")
    print("=" * 100)
    print("Question:", args.question)
    print("Route:", route)
    print("Reason:", routing["reason"])

    context = retrieve_context(
        question=args.question,
        route=route,
        contract_id=args.contract_id,
        top=args.top,
    )

    if args.no_llm:
        print("\n" + "=" * 100)
        print("RETRIEVAL CONTEXT ONLY")
        print("=" * 100)
        print(context)
        return

    if args.show_context:
        print("\n" + "=" * 100)
        print("RETRIEVAL CONTEXT")
        print("=" * 100)
        print(context)

    generator = AnswerGenerator()

    answer = generator.generate(
        question=args.question,
        context=context,
        route=route,
    )

    print("\n" + "=" * 100)
    print("FINAL ANSWER")
    print("=" * 100)
    print(answer)


if __name__ == "__main__":
    main()