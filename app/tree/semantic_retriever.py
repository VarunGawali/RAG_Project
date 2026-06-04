import json

from core.ai_assistant.embedding_service import (
    generate_embedding
)

from core.ai_assistant.search_service import (
    search_client
)
from azure.search.documents.models import VectorizedQuery


class SemanticRetriever:

    def __init__(
        self,
        tree_path: str = None
    ):

        # -----------------------------------------
        # LOAD TREE
        # -----------------------------------------

        self.node_lookup = {}
        self.children_lookup = {}

        if tree_path:

            print("Loading contract tree...")

            with open(tree_path, "r", encoding="utf-8") as f:
                self.tree = json.load(f)

            self._build_tree_indices(self.tree)

            print(
                f"Loaded {len(self.node_lookup)} tree nodes"
            )

    # =====================================================
    # BUILD TREE INDICES
    # =====================================================

    def _build_tree_indices(self, node):

        node_id = node.get("nodeId")

        if node_id:
            self.node_lookup[node_id] = node

        children = node.get("children", [])

        self.children_lookup[node_id] = children

        for child in children:
            self._build_tree_indices(child)

    # =====================================================
    # TREE EXPANSION
    # =====================================================

    def expand_context(self, node_id):

        expanded_nodes = []

        current_node = self.node_lookup.get(node_id)

        if not current_node:
            return expanded_nodes

        # -----------------------------------------
        # CURRENT NODE
        # -----------------------------------------

        expanded_nodes.append(current_node)

        # -----------------------------------------
        # PARENT
        # -----------------------------------------

        parent_id = current_node.get("parentNodeId")

        if parent_id:

            parent_node = self.node_lookup.get(parent_id)

            if (
                parent_node
                and parent_node.get("nodeType") != "document"
            ):
                expanded_nodes.append(parent_node)

        # -----------------------------------------
        # SIBLINGS
        # -----------------------------------------

        if parent_id:

            siblings = self.children_lookup.get(
                parent_id,
                []
            )

            for sibling in siblings:

                if sibling.get("nodeId") != node_id:
                    expanded_nodes.append(sibling)

        # -----------------------------------------
        # CHILDREN
        # -----------------------------------------

        children = self.children_lookup.get(
            node_id,
            []
        )

        expanded_nodes.extend(children)

        return expanded_nodes

    # =====================================================
    # RETRIEVE
    # =====================================================

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        contract_id: str = None
    ):

        print(f"\nGenerating embedding for query:\n{query}")

        query_embedding = generate_embedding(query)

        # -----------------------------------------
        # VECTOR SEARCH
        # -----------------------------------------

        vector_query = VectorizedQuery(
            vector=query_embedding,
            k_nearest_neighbors=top_k,
            fields="embedding"
        )

        filter_expression = None

        if contract_id:

            filter_expression = (
                f"contractId eq '{contract_id}'"
            )

            print(
                f"Searching within contract: "
                f"{contract_id}"
            )

        print("Running Azure AI Search vector query...")

        search_results = search_client.search(
            search_text=None,
            vector_queries=[vector_query],
            top=top_k,
            filter=filter_expression
        )

        results = []

        # -----------------------------------------
        # PROCESS RESULTS
        # -----------------------------------------

        for result in search_results:

            node_id = result.get("nodeId")

            expanded_context = self.expand_context(
                node_id
            )

            results.append({

                # ---------------------------------
                # SEARCH SCORE
                # ---------------------------------

                "score": result.get("@search.score"),

                # ---------------------------------
                # DOCUMENT METADATA
                # ---------------------------------

                "contractId": result.get("contractId"),
                "nodeId": node_id,
                "parentNodeId": result.get(
                    "parentNodeId"
                ),

                "title": result.get("title"),

                "sectionTitle": result.get(
                    "sectionTitle"
                ),

                "clauseTitle": result.get(
                    "clauseTitle"
                ),

                "clauseType": result.get(
                    "clauseType"
                ),

                "pageStart": result.get("pageStart"),
                "pageEnd": result.get("pageEnd"),

                "sourcePath": result.get(
                    "sourcePath"
                ),

                "text": result.get("text"),

                # ---------------------------------
                # HIERARCHICAL CONTEXT
                # ---------------------------------

                "contextExpansion": expanded_context
            })

        return results
