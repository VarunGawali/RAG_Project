# phase4_retriever.py

"""
Hybrid GraphRAG retriever.

Pipeline:
Question
→ vector similarity search
→ semantic entry nodes
→ graph neighborhood expansion
→ supporting graph context
→ merged retrieval context

Used for:
- legal QA
- obligation tracing
- explainability
- graph-enhanced RAG
"""

import json
import logging
from collections import defaultdict


# ============================================================
# UPDATED IMPORTS
# ============================================================

from rag.vector_index import (
    similarity_search,
)

from rag.cosmos_graph import (
    graph_expand,
    get_neighbors,
    gremlin_client,
    resolve_raw_node_id,
)

from gremlin_python.structure.graph import (
    Vertex,
    Edge,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ============================================================
# FORMAT GRAPH PATHS
# ============================================================

"""
def format_graph_paths(paths):
    #Convert Gremlin path output into readable text.
    

    formatted = []

    for path in paths:

        try:

            objects = path.objects

        except AttributeError:

            formatted.append(str(path))
            continue

        parts = []

        for obj in objects:

            # ------------------------------------------------
            # Vertex
            # ------------------------------------------------

            if isinstance(obj, Vertex):

                properties = getattr(
                    obj,
                    "properties",
                    {}
                )

                node_id = properties.get(
                    "id",
                    ["unknown"]
                )[0]

                label = getattr(
                    obj,
                    "label",
                    "Unknown"
                )

                parts.append(
                    f"[{label}: {node_id}]"
                )

            # ------------------------------------------------
            # Edge
            # ------------------------------------------------

            elif isinstance(obj, Edge):

                edge_label = getattr(
                    obj,
                    "label",
                    "RELATED_TO"
                )

                parts.append(
                    f"-[{edge_label}]->"
                )

            # ------------------------------------------------
            # Fallback
            # ------------------------------------------------

            else:

                parts.append(str(obj))

        formatted.append(
            " ".join(parts)
        )

    return formatted
"""

def format_graph_paths(paths):
    """
    Format graph traversal paths.
    """

    formatted = []

    for path in paths:

        try:

            edge = path.get("edge", {})
            neighbor = path.get("neighbor", {})

            edge_label = edge.get(
                "label",
                "RELATED_TO"
            )

            neighbor_label = neighbor.get(
                "label",
                "Unknown"
            )

            neighbor_id = neighbor.get(
                "id",
                "unknown"
            )

            properties = neighbor.get(
                "properties",
                {}
            )

            title = "Untitled"

            candidate_fields = [

                "title",
                "name",
                "entityName",
                "canonicalName",
                "value",
                "text",
            ]

            for field in candidate_fields:

                if field in properties:

                    try:

                        title = properties[field][0].get(
                            "value",
                            "Untitled"
                        )

                        break

                    except Exception:
                        pass

            formatted.append(

                f"-[{edge_label}]-> "
                f"[{neighbor_label}] "
                f"{title}"

            )

        except Exception as e:

            formatted.append(
                f"Path formatting error: {e}"
            )

    return formatted

# ============================================================
# FORMAT NEIGHBORS
# ============================================================

def get_vertex_properties(vertex):

    try:

        props = {}

        for key, value in vertex.properties.items():

            if isinstance(value, list):

                props[key] = value[0]

            else:

                props[key] = value

        return props

    except Exception:

        return {}

"""
def format_neighbors(neighbors):
    

    formatted = []

    for item in neighbors:

        try:

            edge = item["edge"]

            neighbor = item["neighbor"]

            rel = edge.label

            neighbor_props = getattr(
                neighbor,
                "properties",
                {}
            )

            neighbor_id = neighbor_props.get(
                "id",
                ["unknown"]
            )[0]

            neighbor_label = getattr(
                neighbor,
                "label",
                "Unknown"
            )

            formatted.append(
                f"-[{rel}]-> "
                f"[{neighbor_label}: {neighbor_id}]"
            )

        except Exception:

            formatted.append(str(item))

    return formatted
"""
def format_neighbors(neighbors):
    """
    Format graph neighbors into readable text.
    """

    formatted = []

    for item in neighbors:

        try:

            edge = item.get("edge", {})
            neighbor = item.get("neighbor", {})

            # ----------------------------------------
            # EDGE LABEL
            # ----------------------------------------

            edge_label = edge.get(
                "label",
                "RELATED_TO"
            )

            # ----------------------------------------
            # NEIGHBOR INFO
            # ----------------------------------------

            neighbor_id = neighbor.get(
                "id",
                "unknown"
            )

            neighbor_label = neighbor.get(
                "label",
                "Unknown"
            )

            properties = neighbor.get(
                "properties",
                {}
            )

            title = "Untitled"

            candidate_fields = [

                "title",
                "name",
                "entityName",
                "canonicalName",
                "value",
                "text",
            ]

            for field in candidate_fields:

                if field in properties:

                    try:

                        title = properties[field][0].get(
                            "value",
                            "Untitled"
                        )

                        break

                    except Exception:
                        pass

            formatted.append(

                f"-[{edge_label}]-> "
                f"[{neighbor_label}] "
                f"{title}"

            )

        except Exception as e:

            formatted.append(
                f"Formatting error: {e}"
            )

    return formatted

# ============================================================
# HYBRID GRAPHRAG RETRIEVAL
# ============================================================


def graph_rag_retrieve(
    question,
    k=4,
    hops=2,
    contract_id=None,
):
    """
    Hybrid retrieval:
    1. Vector similarity search
    2. Graph expansion
    3. Context assembly
    """

    logger.info(
        f"Running GraphRAG retrieval "
        f"for: {question}"
    )

    # ========================================================
    # VECTOR SEARCH
    # ========================================================

    docs = similarity_search(
        query=question,
        top_k=k,
        contract_id=contract_id,
    )

    logger.info(
        f"Retrieved {len(docs)} "
        f"semantic entry nodes"
    )

    context_parts = []

    seen_nodes = set()

    # ========================================================
    # EXPAND EACH ENTRY NODE
    # ========================================================

    for i, doc in enumerate(docs, start=1):

        # ----------------------------------------------------
        # IMPORTANT:
        # docs are now plain dicts
        # NOT LangChain Document objects
        # ----------------------------------------------------

        metadata = doc

        # ----------------------------------------------------
        # IMPORTANT:
        # use nodeId for graph traversal
        # NOT Azure Search document id
        # ----------------------------------------------------

        #node_id = metadata.get(
        #    "nodeId",
        #   "unknown"
        #) (temporaryly disabled to test raw node ID resolution)

        raw_node_id = metadata.get(
            "nodeId",
            "unknown"
        )

        node_id = resolve_raw_node_id(
            raw_node_id
        )

        if not node_id:
            continue

        if (
            not node_id
            or node_id == "unknown"
        ):
            continue

        if node_id in seen_nodes:
            continue

        seen_nodes.add(node_id)

        logger.info(
            f"Expanding node: {node_id}"
        )

        # ----------------------------------------------------
        # GRAPH NEIGHBORS
        # ----------------------------------------------------

        neighbors = get_neighbors(node_id)

        formatted_neighbors = format_neighbors(
            neighbors
        )

        # ----------------------------------------------------
        # MULTI-HOP EXPANSION
        # ----------------------------------------------------

        paths = graph_expand(
            node_id=node_id,
            hops=hops
        )

        formatted_paths = format_graph_paths(
            paths
        )

        # ====================================================
        # BUILD CONTEXT
        # ====================================================

        context_parts.append(
            "=" * 60
        )

        context_parts.append(
            f"ENTRY NODE {i}: {node_id}"
        )

        context_parts.append(
            "=" * 60
        )

        # ----------------------------------------------------
        # VECTOR RETRIEVAL CONTENT
        # ----------------------------------------------------

        context_parts.append(
            "\nSEMANTIC MATCH:\n"
        )

        context_parts.append(
            doc.get("text", "")
        )

        # ----------------------------------------------------
        # SEARCH SCORE
        # ----------------------------------------------------

        score = metadata.get(
            "score"
        )

        if score is not None:

            context_parts.append(
                f"\nSEARCH SCORE: {score}"
            )

        # ----------------------------------------------------
        # METADATA
        # ----------------------------------------------------

        if metadata:

            context_parts.append(
                "\nMETADATA:"
            )

            important_keys = [

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
            ]

            for key in important_keys:

                value = metadata.get(key)

                if value is not None:

                    context_parts.append(
                        f"- {key}: {value}"
                    )

        # ----------------------------------------------------
        # DIRECT NEIGHBORS
        # ----------------------------------------------------

        if formatted_neighbors:

            context_parts.append(
                "\nDIRECT GRAPH NEIGHBORS:"
            )

            context_parts.extend(
                formatted_neighbors[:15]
            )

        # ----------------------------------------------------
        # MULTI-HOP PATHS
        # ----------------------------------------------------

        if formatted_paths:

            context_parts.append(
                f"\nGRAPH PATHS "
                f"(up to {hops} hops):"
            )

            context_parts.extend(
                formatted_paths[:10]
            )

        context_parts.append("\n")

    # ========================================================
    # FINAL CONTEXT
    # ========================================================

    final_context = "\n".join(
        context_parts
    )

    logger.info(
        "GraphRAG retrieval complete"
    )

    return final_context

# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    question = (
        "If the Buyer defaults, "
        "what remedies and payment "
        "obligations are triggered?"
    )

    
    context = graph_rag_retrieve(
        question=question,
        k=4,
        hops=2,
        contract_id="Edison_NYPA_OandM_Contract_1",
    )


    print("\n")
    print("=" * 80)
    print("GRAPHRAG RETRIEVAL CONTEXT")
    print("=" * 80)
    print(context)
