"""
Hybrid GraphRAG retriever for Contract360 demo.

Flow:
Question
→ Azure AI Search hybrid/vector search over tree chunks
→ Search result contains kgId
→ Cosmos Gremlin expands graph context around kgId
→ Context assembled for answer generation

Important:
- Azure AI Search is the semantic/vector search layer.
- Cosmos Gremlin is the symbolic graph traversal layer.
- Gremlin does not currently have embeddings.
- Azure Search docs should contain:
    kgId, parentKgId, graphReady, nodeType, graphLabel
"""

import logging
from typing import Any, Dict, List, Optional

from app.indexing.search_tester import AzureSearchTester
from app.kg.gremlin_writer import GremlinWriter


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# ============================================================
# Graph expansion settings
# ============================================================

DEFAULT_EDGE_LABELS = [
    "HAS_PARENT",
    "NEXT_SIBLING",
    "PREVIOUS_SIBLING",

    "EXTRACTED_ENTITY",
    "IMPOSES_OBLIGATION",
    "GRANTS_RIGHT",
    "PROHIBITS",

    "OWED_BY",
    "OWED_TO",
    "HAS_DEADLINE",
    "HAS_NOTICE_PERIOD",
    "HAS_FREQUENCY",
    "SUBJECT_TO",
    "TRIGGERED_BY",
    "HAS_RISK_SIGNAL",
]


DISPLAY_FIELDS = [
    "title",
    "name",
    "legalType",
    "nodeType",
    "sectionNumber",
    "sourceClauseId",
    "evidenceQuote",
    "textPreview",
]


# ============================================================
# Helpers
# ============================================================

def first_value(prop_map: Dict[str, Any], key: str, default=None):
    """
    Cosmos Gremlin valueMap usually returns values as lists.
    Example:
        {"name": ["Con Edison"]}

    This helper safely extracts the first value.
    """
    if not prop_map:
        return default

    value = prop_map.get(key, default)

    if isinstance(value, list):
        if not value:
            return default
        first = value[0]
        if isinstance(first, dict) and "value" in first:
            return first.get("value", default)
        return first

    if isinstance(value, dict) and "value" in value:
        return value.get("value", default)

    return value


def short_text(value: Any, limit: int = 300) -> str:
    if value is None:
        return ""

    text = str(value).replace("\n", " ").strip()

    if len(text) > limit:
        return text[:limit] + "...[truncated]"

    return text


def display_name_from_props(props: Dict[str, Any]) -> str:
    """
    Pick the best human-readable display text from vertex properties.
    """
    for field in DISPLAY_FIELDS:
        value = first_value(props, field)
        if value:
            return short_text(value, limit=250)

    return "Untitled"


# ============================================================
# Gremlin graph retriever
# ============================================================

class GraphContextRetriever:
    """
    Lightweight Cosmos Gremlin graph context retriever.

    Uses simple per-edge-label queries for Cosmos compatibility.
    Avoids complex optional/select/path traversals.
    """

    def __init__(self):
        self.writer = GremlinWriter()

    def close(self):
        self.writer.close()

    def resolve_raw_node_id(self, raw_node_id: str) -> Optional[str]:
        """
        Fallback only.

        Azure AI Search should now return kgId directly.
        This is used only when kgId is missing.
        """
        if not raw_node_id or raw_node_id == "unknown":
            return None

        query = """
        g.V().
          has('rawNodeId', raw_node_id).
          limit(1).
          valueMap('kgId')
        """

        result = self.writer.submit(query, {"raw_node_id": raw_node_id})

        if not result:
            return None

        return first_value(result[0], "kgId")

    def get_vertex_metadata(self, kg_id: str) -> Dict[str, Any]:
        """
        Get metadata for a graph vertex.
        """
        query = """
        g.V(kg_id).
          project('id', 'label', 'props').
            by(id()).
            by(label()).
            by(valueMap(
                'kgId',
                'contractId',
                'tenantId',
                'nodeType',
                'legalType',
                'title',
                'name',
                'pageStart',
                'pageEnd',
                'sourcePath',
                'sourceClauseId',
                'evidenceQuote',
                'textPreview',
                'confidence'
            ))
        """

        result = self.writer.submit(query, {"kg_id": kg_id})

        if not result:
            return {}

        return result[0]

    def get_neighbors_by_edge(
        self,
        kg_id: str,
        edge_label: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve neighbors connected through a specific edge label.

        Uses bothE because search entry nodes can be Clause vertices and
        relationships may be incoming or outgoing depending on edge type.

        Edge labels are internal allowlisted constants, not user input.
        """

        query = f"""
        g.V(kg_id).
          bothE('{edge_label}').
          otherV().
          dedup().
          limit(neighbor_limit).
          project('id', 'label', 'props').
            by(id()).
            by(label()).
            by(valueMap(
                'kgId',
                'contractId',
                'tenantId',
                'nodeType',
                'legalType',
                'title',
                'name',
                'pageStart',
                'pageEnd',
                'sourcePath',
                'sourceClauseId',
                'evidenceQuote',
                'textPreview',
                'confidence'
            ))
        """

        try:
            result = self.writer.submit(
                query,
                {
                    "kg_id": kg_id,
                    "neighbor_limit": limit,
                },
            )

            for item in result:
                item["edgeLabel"] = edge_label

            return result

        except Exception as exc:
            logger.warning(
                f"Neighbor query failed for edge={edge_label}, kgId={kg_id}: {exc}"
            )
            return []

    def get_graph_context(
        self,
        kg_id: str,
        edge_labels: Optional[List[str]] = None,
        per_edge_limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve graph context around one vertex.
        """
        edge_labels = edge_labels or DEFAULT_EDGE_LABELS

        all_neighbors: List[Dict[str, Any]] = []

        for edge_label in edge_labels:
            neighbors = self.get_neighbors_by_edge(
                kg_id=kg_id,
                edge_label=edge_label,
                limit=per_edge_limit,
            )
            all_neighbors.extend(neighbors)

        return all_neighbors


# ============================================================
# Formatting
# ============================================================

def format_vertex(item: Dict[str, Any]) -> str:
    """
    Format one projected graph vertex.
    """
    vertex_id = item.get("id", "unknown")
    label = item.get("label", "Unknown")
    props = item.get("props", {}) or {}

    title = display_name_from_props(props)

    page_start = first_value(props, "pageStart")
    page_end = first_value(props, "pageEnd")
    source_path = first_value(props, "sourcePath")
    evidence = first_value(props, "evidenceQuote")
    confidence = first_value(props, "confidence")
    source_clause_id = first_value(props, "sourceClauseId")

    parts = [
        f"[{label}] {title}",
        f"id: {vertex_id}",
    ]

    if confidence is not None:
        parts.append(f"confidence: {confidence}")

    if page_start is not None:
        if page_end is not None:
            parts.append(f"pages: {page_start}-{page_end}")
        else:
            parts.append(f"page: {page_start}")

    if source_clause_id:
        parts.append(f"sourceClauseId: {source_clause_id}")

    if source_path:
        parts.append(f"sourcePath: {source_path}")

    if evidence:
        parts.append(f'evidence: "{short_text(evidence, 350)}"')

    return " | ".join(parts)


def format_graph_context(neighbors: List[Dict[str, Any]]) -> List[str]:
    """
    Format graph neighbors grouped by edge label.
    """
    if not neighbors:
        return ["- No graph context found."]

    lines: List[str] = []

    for item in neighbors:
        edge_label = item.get("edgeLabel", "RELATED_TO")
        vertex_text = format_vertex(item)
        lines.append(f"-[{edge_label}]- {vertex_text}")

    return lines


# ============================================================
# Hybrid GraphRAG retrieval
# ============================================================

def graph_rag_retrieve(
    question: str,
    k: int = 4,
    contract_id: Optional[str] = "Edison_NYPA_OandM_Contract_1",
    graph_ready_only: bool = True,
) -> str:
    """
    Hybrid GraphRAG retrieval.

    For demo:
    - Use Azure AI Search to find relevant clause chunks.
    - Prefer graphReady docs with kgId.
    - Expand each kgId in Cosmos Gremlin.
    - Assemble context for LLM answer generation.

    Args:
        question:
            User question.

        k:
            Number of search results to keep.

        contract_id:
            Optional contract filter. For demo, keep Edison contract.

        graph_ready_only:
            If True, only keep search docs with kgId/graphReady.

    Returns:
        A context string.
    """

    logger.info(f"Running hybrid GraphRAG retrieval for: {question}")

    searcher = AzureSearchTester()

    # Fetch more than k, then filter graph-ready if needed.
    # This matters if index contains old non-graph-ready docs.
    search_top = max(k * 5, k)

    docs = searcher.hybrid_search(
        query=question,
        contract_id=contract_id,
        top=search_top,
    )

    logger.info(f"Azure AI Search returned {len(docs)} docs")

    if graph_ready_only:
        docs = [
            d for d in docs
            if d.get("graphReady") is True and d.get("kgId")
        ]
        logger.info(f"Graph-ready docs after filtering: {len(docs)}")

    docs = docs[:k]

    if not docs:
        return (
            "No graph-ready Azure AI Search results found for this question. "
            "Try using search-only mode or verify that kgId/graphReady fields "
            "exist in the Azure AI Search index."
        )

    graph = GraphContextRetriever()

    context_parts: List[str] = []
    seen_nodes = set()

    try:
        for i, doc in enumerate(docs, start=1):
            kg_id = doc.get("kgId")

            if kg_id:
                logger.info(f"Using kgId from Azure AI Search: {kg_id}")
            else:
                raw_node_id = doc.get("nodeId", "unknown")
                logger.info(f"kgId missing; resolving raw nodeId: {raw_node_id}")
                kg_id = graph.resolve_raw_node_id(raw_node_id)

            if not kg_id:
                logger.warning("Skipping doc because no graph node id was found.")
                continue

            if kg_id in seen_nodes:
                logger.info(f"Skipping duplicate graph node: {kg_id}")
                continue

            seen_nodes.add(kg_id)

            logger.info(f"Expanding graph context for: {kg_id}")

            graph_context = graph.get_graph_context(
                kg_id=kg_id,
                per_edge_limit=8,
            )

            formatted_graph_context = format_graph_context(graph_context)

            # ------------------------------------------------
            # Assemble context
            # ------------------------------------------------

            context_parts.append("=" * 100)
            context_parts.append(f"SEARCH RESULT {i}")
            context_parts.append("=" * 100)

            context_parts.append("\nAZURE AI SEARCH MATCH:")
            context_parts.append(short_text(doc.get("text", ""), 2000))

            score = (
                doc.get("@search.score")
                or doc.get("score")
                or doc.get("@search.reranker_score")
            )

            if score is not None:
                context_parts.append(f"\nSEARCH SCORE: {score}")

            context_parts.append("\nSOURCE METADATA:")
            metadata_keys = [
                "title",
                "sectionTitle",
                "clauseTitle",
                "clauseType",
                "pageStart",
                "pageEnd",
                "sourcePath",
                "contractId",
                "documentId",
                "itemType",
                "nodeId",
                "parentNodeId",
                "kgId",
                "parentKgId",
                "graphReady",
                "nodeType",
                "graphLabel",
            ]

            for key in metadata_keys:
                value = doc.get(key)
                if value is not None:
                    context_parts.append(f"- {key}: {value}")

            context_parts.append("\nCOSMOS GREMLIN GRAPH CONTEXT:")
            context_parts.extend(formatted_graph_context[:30])

            context_parts.append("\n")

    finally:
        graph.close()

    final_context = "\n".join(context_parts)

    logger.info("Hybrid GraphRAG retrieval complete")

    return final_context


# ============================================================
# Test
# ============================================================

if __name__ == "__main__":
    test_question = (
        "If a Breach is not cured, what remedies does the "
        "non-Breaching Party have?"
    )

    context = graph_rag_retrieve(
        question=test_question,
        k=4,
        contract_id="Edison_NYPA_OandM_Contract_1",
        graph_ready_only=True,
    )

    print("\n")
    print("=" * 100)
    print("HYBRID GRAPHRAG RETRIEVAL CONTEXT")
    print("=" * 100)
    print(context)