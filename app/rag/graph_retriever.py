"""
Graph-native retriever for Contract360 demo.

Use this for structured graph questions:
- What obligations does Con Edison have?
- Which obligations are owed to Power Authority?
- Which obligations have deadlines?
- Which rights are granted?
- Which restrictions exist?

This does NOT start with Azure AI Search.
It directly queries Cosmos Gremlin semantic KG.
"""

import logging
from typing import Any, Dict, List, Optional

from app.kg.gremlin_writer import GremlinWriter


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


PARTY_ALIASES = {
    "con edison": "Con Edison",
    "consolidated edison": "Con Edison",
    "power authority": "Power Authority",
    "nypa": "Power Authority",
    "new york power authority": "Power Authority",
    "either party": "Either Party",
    "breaching party": "Breaching Party",
    "non-breaching party": "Non-Breaching Party",
}


def first_value(prop_map: Dict[str, Any], key: str, default=None):
    value = prop_map.get(key, default)

    if isinstance(value, list):
        if not value:
            return default
        return value[0]

    return value


def extract_party(question: str) -> Optional[str]:
    q = question.lower()

    for alias, canonical in PARTY_ALIASES.items():
        if alias in q:
            return canonical

    return None


def normalize_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized = []

    for item in items:
        normalized.append({
            "kgId": first_value(item, "kgId"),
            "name": first_value(item, "name"),
            "confidence": first_value(item, "confidence"),
            "evidenceQuote": first_value(item, "evidenceQuote"),
            "sourceClauseId": first_value(item, "sourceClauseId"),
        })

    return normalized


class GraphNativeRetriever:
    def __init__(self):
        self.writer = GremlinWriter()

    def close(self):
        self.writer.close()

    def get_obligations_by_party(self, party_name: str) -> List[Dict[str, Any]]:
        """
        Pattern:
        Party <- OWED_BY - Obligation
        """
        query = """
        g.V().
          hasLabel('Party').
          has('name', party_name).
          in('OWED_BY').
          hasLabel('Obligation').
          dedup().
          valueMap('kgId', 'name', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """

        result = self.writer.submit(query, {"party_name": party_name})
        return normalize_items(result)

    def get_obligations_owed_to_party(self, party_name: str) -> List[Dict[str, Any]]:
        """
        Pattern:
        Party <- OWED_TO - Obligation
        """
        query = """
        g.V().
          hasLabel('Party').
          has('name', party_name).
          in('OWED_TO').
          hasLabel('Obligation').
          dedup().
          valueMap('kgId', 'name', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """

        result = self.writer.submit(query, {"party_name": party_name})
        return normalize_items(result)

    def get_obligations_with_deadlines(self) -> List[Dict[str, Any]]:
        query = """
        g.V().
          hasLabel('Obligation').
          as('obligation').
          out('HAS_DEADLINE').
          hasLabel('Deadline').
          as('deadline').
          select('obligation', 'deadline').
            by(valueMap('kgId', 'name', 'confidence', 'evidenceQuote', 'sourceClauseId')).
            by(valueMap('kgId', 'name', 'evidenceQuote'))
        """

        result = self.writer.submit(query)

        items = []

        for row in result:
            obligation = row.get("obligation", {})
            deadline = row.get("deadline", {})

            items.append({
                "kgId": first_value(obligation, "kgId"),
                "name": first_value(obligation, "name"),
                "confidence": first_value(obligation, "confidence"),
                "evidenceQuote": first_value(obligation, "evidenceQuote"),
                "sourceClauseId": first_value(obligation, "sourceClauseId"),
                "deadlineName": first_value(deadline, "name"),
                "deadlineEvidence": first_value(deadline, "evidenceQuote"),
            })

        return items

    def get_rights(self) -> List[Dict[str, Any]]:
        query = """
        g.V().
          hasLabel('Right').
          dedup().
          valueMap('kgId', 'name', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """

        result = self.writer.submit(query)
        return normalize_items(result)

    def get_restrictions(self) -> List[Dict[str, Any]]:
        query = """
        g.V().
          hasLabel('Restriction').
          dedup().
          valueMap('kgId', 'name', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """

        result = self.writer.submit(query)
        return normalize_items(result)

    def get_clause_metadata(self, source_clause_id: str) -> Dict[str, Any]:
        query = """
        g.V(source_clause_id).
          valueMap('kgId', 'title', 'pageStart', 'pageEnd', 'sourcePath', 'textPreview')
        """

        result = self.writer.submit(query, {"source_clause_id": source_clause_id})

        if not result:
            return {}

        row = result[0]

        return {
            "kgId": first_value(row, "kgId"),
            "title": first_value(row, "title"),
            "pageStart": first_value(row, "pageStart"),
            "pageEnd": first_value(row, "pageEnd"),
            "sourcePath": first_value(row, "sourcePath"),
            "textPreview": first_value(row, "textPreview"),
        }


def format_graph_facts(
    question: str,
    intent: str,
    facts: List[Dict[str, Any]],
    retriever: GraphNativeRetriever,
) -> str:
    lines = []

    lines.append("GRAPH-NATIVE RETRIEVAL")
    lines.append("=" * 80)
    lines.append(f"Question: {question}")
    lines.append(f"Intent: {intent}")
    lines.append(f"Facts found: {len(facts)}")
    lines.append("")

    if not facts:
        lines.append("No graph facts found.")
        return "\n".join(lines)

    for idx, fact in enumerate(facts, start=1):
        source_clause_id = fact.get("sourceClauseId")
        clause_meta = (
            retriever.get_clause_metadata(source_clause_id)
            if source_clause_id
            else {}
        )

        lines.append("-" * 80)
        lines.append(f"Fact {idx}")
        lines.append(f"Name: {fact.get('name')}")

        if fact.get("deadlineName"):
            lines.append(f"Deadline: {fact.get('deadlineName')}")

        if fact.get("deadlineEvidence"):
            lines.append(f"Deadline evidence: {fact.get('deadlineEvidence')}")

        if fact.get("confidence") is not None:
            lines.append(f"Confidence: {fact.get('confidence')}")

        if fact.get("evidenceQuote"):
            lines.append(f"Evidence: {fact.get('evidenceQuote')}")

        if clause_meta:
            lines.append(f"Source clause: {clause_meta.get('title')}")
            lines.append(
                f"Pages: {clause_meta.get('pageStart')}-{clause_meta.get('pageEnd')}"
            )
            lines.append(f"Source path: {clause_meta.get('sourcePath')}")

    return "\n".join(lines)


def graph_native_retrieve(question: str) -> str:
    q = question.lower()

    retriever = GraphNativeRetriever()

    try:
        party = extract_party(question)

        if "deadline" in q or "due" in q or "by when" in q:
            facts = retriever.get_obligations_with_deadlines()
            return format_graph_facts(
                question,
                "obligations_with_deadlines",
                facts,
                retriever,
            )

        if "owed to" in q and party:
            facts = retriever.get_obligations_owed_to_party(party)
            return format_graph_facts(
                question,
                f"obligations_owed_to_party:{party}",
                facts,
                retriever,
            )

        if ("obligation" in q or "responsible" in q or "owe" in q or "owed" in q) and party:
            facts = retriever.get_obligations_by_party(party)
            return format_graph_facts(
                question,
                f"obligations_by_party:{party}",
                facts,
                retriever,
            )

        if "right" in q:
            facts = retriever.get_rights()
            return format_graph_facts(
                question,
                "rights",
                facts,
                retriever,
            )

        if "restriction" in q or "prohibit" in q or "shall not" in q:
            facts = retriever.get_restrictions()
            return format_graph_facts(
                question,
                "restrictions",
                facts,
                retriever,
            )

        return (
            "Graph-native retriever could not identify a supported graph intent. "
            "Use hybrid retrieval for this question."
        )

    finally:
        retriever.close()


if __name__ == "__main__":
    questions = [
        "What obligations does Con Edison have?",
        "What obligations does Power Authority have?",
        "Which obligations are owed to Power Authority?",
        "Which obligations have deadlines?",
        "Which rights are granted?",
    ]

    for question in questions:
        print("\n" + "=" * 100)
        print(question)
        print("=" * 100)
        print(graph_native_retrieve(question))