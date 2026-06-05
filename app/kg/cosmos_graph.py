# phase4_cosmos_graph.py

"""
Cosmos DB Gremlin graph retrieval utilities.

Provides:
1. Cosmos Gremlin client
2. Multi-hop graph traversal
3. Neighbor retrieval
4. Path expansion for GraphRAG

Used by:
- graph-enhanced retrieval
- obligation tracing
- explainability
- cross-clause linking
"""

import os
import json
import logging

from gremlin_python.driver import client
from gremlin_python.driver.serializer import (
    GraphSONSerializersV2d0
)

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ============================================================
# COSMOS GREMLIN CLIENT
# ============================================================

required_env = [
    "GREMLIN_ENDPOINT",
    "GREMLIN_DATABASE",
    "GREMLIN_GRAPH",
    "GREMLIN_PASSWORD",
]

missing = [
    v for v in required_env
    if not os.getenv(v)
]

if missing:
    raise ValueError(
        f"Missing environment variables: {missing}"
    )

GREMLIN_ENDPOINT = os.getenv(
    "GREMLIN_ENDPOINT"
)

GREMLIN_DATABASE = os.getenv(
    "GREMLIN_DATABASE"
)

GREMLIN_GRAPH = os.getenv(
    "GREMLIN_GRAPH"
)

GREMLIN_KEY = os.getenv(
    "GREMLIN_PASSWORD"
)

# ------------------------------------------------------------
# Cosmos username format:
# /dbs/<db>/colls/<graph>
# ------------------------------------------------------------

GREMLIN_USERNAME = (
    f"/dbs/{GREMLIN_DATABASE}"
    f"/colls/{GREMLIN_GRAPH}"
)

gremlin_client = client.Client(
    GREMLIN_ENDPOINT,
    "g",
    username=GREMLIN_USERNAME,
    password=GREMLIN_KEY,
    message_serializer=GraphSONSerializersV2d0(),
)

logger.info("Connected to Cosmos Gremlin API")


# ============================================================
# LEGAL ONTOLOGY
# ============================================================

LEGAL_RELATIONSHIPS = [

    # semantic edges

    "EXTRACTED_ENTITY",
    "IMPOSES_OBLIGATION",
    "GRANTS_RIGHT",
    "OWED_BY",
    "OWED_TO",
    "HAS_DEADLINE",
    "HAS_NOTICE_PERIOD",
    "HAS_FREQUENCY",
    "SUBJECT_TO",
    "TRIGGERED_BY",

    # optional semantic edges

    "PROHIBITS",
    "HELD_BY",
    "EXCEPTS",
    "APPLIES_TO",
    "RECORDED_IN",
    "REQUIRES",
    "HAS_RISK_SIGNAL",

    # structural edges

    "CONTAINS_SECTION",
    "CONTAINS_CLAUSE",
    "HAS_PARENT",
    "NEXT_SIBLING",
    "PREVIOUS_SIBLING",
    "HAS_APPENDIX",
    "HAS_EXHIBIT",
]

LEGAL_NODE_LABELS = [

    # structural

    "Contract",
    "Section",
    "Clause",
    "Appendix",
    "Exhibit",

    # semantic

    "Party",
    "Obligation",
    "Right",
    "Restriction",
    "Deadline",
    "NoticePeriod",
    "Frequency",
    "Asset",
    "Event",
    "RiskSignal",

    # candidate labels

    "Condition",
    "Exception",
    "MonetaryAmount",
    "System",
    "Report",
]

# ============================================================
# GRAPH EXPANSION
# ============================================================

def graph_expand(
    node_id: str,
    hops: int = 2,
    allowed_edges=None,
    allowed_labels=None,
):
    """
    Expand graph neighborhood around a node.

    Args:
        node_id:
            Canonical entity ID

        hops:
            Traversal depth

        allowed_edges:
            List of allowed edge types

        allowed_labels:
            List of allowed node labels

    Returns:
        List of graph paths
    """

    if allowed_edges is None:
        allowed_edges = LEGAL_RELATIONSHIPS

    if allowed_labels is None:
        allowed_labels = LEGAL_NODE_LABELS

    edge_string = ", ".join(
        [f"'{e}'" for e in allowed_edges]
    )

    label_string = ", ".join(
        [f"'{l}'" for l in allowed_labels]
    )

    query = f"""
    g.V()
    .has('id', '{node_id}')
    .bothE({edge_string})
    .as('edge')
    .otherV()
    .hasLabel({label_string})
    .as('neighbor')
    .select('edge', 'neighbor')
    """

    logger.info(
        f"Running graph expansion for "
        f"'{node_id}' "
        f"(hops={hops})"
    )

    try:

        result = (
            gremlin_client
            .submit(query)
            .all()
            .result()
        )

        logger.info(
            f"Retrieved {len(result)} paths"
        )

        return result

    except Exception as e:

        logger.error(
            f"Graph expansion failed: {e}"
        )

        return []

# ============================================================
# DIRECT NEIGHBOR RETRIEVAL
# ============================================================

def get_neighbors(node_id: str):
    """
    Retrieve direct neighbors of a node.
    """

    query = f"""
    g.V()
     .has('id', '{node_id}')
     .bothE()
     .as('edge')
     .otherV()
     .as('neighbor')
     .select('edge', 'neighbor')
    """

    try:

        result = (
            gremlin_client
            .submit(query)
            .all()
            .result()
        )

        return result

    except Exception as e:

        logger.error(
            f"Neighbor retrieval failed: {e}"
        )

        return []

# ============================================================
# PATH EXPLAINABILITY
# ============================================================

def explain_path(
    source_id: str,
    target_id: str,
    max_hops: int = 4
):
    """
    Find graph paths between two entities.

    Useful for:
    - explainability
    - legal reasoning
    - obligation tracing
    """

    query = f"""
    g.V()
     .has('id', '{source_id}')
     .repeat(
         bothE()
         .otherV()
         .simplePath()
     )
     .until(
         has('id', '{target_id}')
     )
     .times({max_hops})
     .path()
    """

    try:

        result = (
            gremlin_client
            .submit(query)
            .all()
            .result()
        )

        return result

    except Exception as e:

        logger.error(
            f"Path explanation failed: {e}"
        )

        return []
    
# Graph Id replacement code (temporary)
def resolve_raw_node_id(raw_node_id):

    query = f"""
    g.V()
     .has('rawNodeId', '{raw_node_id}')
     .limit(1)
     .valueMap(true)
    """

    try:

        result = (
            gremlin_client
            .submit(query)
            .all()
            .result()
        )

        if not result:
            return None

        vertex = result[0]

        kg_id = vertex.get(
            "kgId",
            [None]
        )[0]

        return kg_id

    except Exception as e:

        logger.error(
            f"Failed resolving raw node ID: {e}"
        )

        return None

# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print("\n====================================")
    print("COSMOS GRAPH TEST")
    print("====================================")

    
    test_node = (
        "obligation:"
        "Edison_NYPA_OandM_Contract_1:"
        "ConEdison_Notify_New_Removed_Chemicals"
    )


    neighbors = get_neighbors(test_node)

    print(
        f"\nNeighbors for '{test_node}':"
    )

    print(
        json.dumps(
            neighbors[:5],
            indent=2,
            default=str
        )
    )

    expanded = graph_expand(
        test_node,
        hops=2
    )

    print(
        f"\nExpanded paths:"
    )

    print(
        json.dumps(
            expanded[:3],
            indent=2,
            default=str
        )
    )