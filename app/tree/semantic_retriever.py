import json
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from core.ai_assistant.embedding_service import generate_query_embedding


class SemanticRetriever:

    def __init__(
        self,
        corpus_path: str,
        tree_path: str = None
    ):

        print("Loading corpus...")

        with open(corpus_path, "r", encoding="utf-8") as f:
            self.documents = json.load(f)

        print(f"Loaded {len(self.documents)} chunks")

        self.embeddings = np.array([
            doc["embedding"]
            for doc in self.documents
        ])

        print("Embeddings matrix ready")

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

    def _build_tree_indices(self, node):
        node_id = node.get("nodeId")
        if node_id:
            self.node_lookup[node_id] = node

        children = node.get("children", [])
        self.children_lookup[node_id] = children

        for child in children:
            self._build_tree_indices(child)

    def expand_context(self, node_id):

        expanded_nodes = []
        current_node = self.node_lookup.get(node_id)

        if not current_node:
            return expanded_nodes

        # -----------------------------------------
        # ADD CURRENT NODE
        # -----------------------------------------

        expanded_nodes.append(current_node)

        # -----------------------------------------
        # ADD PARENT
        # -----------------------------------------

        parent_id = current_node.get("parentNodeId")
        if parent_id:
            parent_node = self.node_lookup.get(parent_id)

            if parent_node:
                if parent_node.get("nodeType") != "document":
                    expanded_nodes.append(parent_node)

        # -----------------------------------------
        # ADD SIBLINGS
        # -----------------------------------------

        if parent_id:
            siblings = []
            parent_node = self.node_lookup.get(parent_id)

            if parent_node:
                parent_type = parent_node.get("nodeType")

                if parent_type != "document":
                    siblings = self.children_lookup.get(parent_id, [])
                    
            parent_node = self.node_lookup.get(parent_id)

            if parent_node:
                parent_type = parent_node.get("nodeType")
                if parent_type != "document":
                    siblings = self.children_lookup.get(parent_id, [])

            for sibling in siblings:
                if sibling.get("nodeId") != node_id:
                    expanded_nodes.append(sibling)

        # -----------------------------------------
        # ADD CHILDREN
        # -----------------------------------------

        children = self.children_lookup.get(node_id, [])
        expanded_nodes.extend(children)

        return expanded_nodes

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        contract_id: str = None
    ):

        print(f"\nGenerating embedding for query:\n{query}")

        query_embedding = generate_query_embedding(query)

        query_embedding = np.array(query_embedding).reshape(1, -1)

        # -----------------------------------------
        # FILTER DOCUMENTS BY CONTRACT
        # -----------------------------------------

        filtered_docs = self.documents

        if contract_id:

            filtered_docs = [
                doc for doc in self.documents
                if doc.get("contractId") == contract_id
            ]

            print(
                f"Searching within contract: {contract_id}"
            )

            print(
                f"Filtered chunks: {len(filtered_docs)}"
            )

        # -----------------------------------------
        # BUILD FILTERED EMBEDDING MATRIX
        # -----------------------------------------

        filtered_embeddings = np.array([
            doc["embedding"]
            for doc in filtered_docs
        ])

        # -----------------------------------------
        # COSINE SIMILARITY
        # -----------------------------------------

        similarities = cosine_similarity(
            query_embedding,
            filtered_embeddings
        )[0]

        top_indices = [
            idx
            for idx in similarities.argsort()[::-1]
            if similarities[idx] > 0.45
        ][:top_k]

        results = []

        for idx in top_indices:

            doc = filtered_docs[idx]

            # -----------------------------------------
            # TREE-BASED CONTEXT EXPANSION
            # -----------------------------------------

            expanded_context = self.expand_context(
                doc.get("nodeId")
            )

            results.append({
                "score": float(similarities[idx]),
                "contractId": doc.get("contractId"),
                "nodeId": doc.get("nodeId"),
                "parentNodeId": doc.get("parentNodeId"),
                "title": doc.get("title"),
                "sectionTitle": doc.get("sectionTitle"),
                "clauseTitle": doc.get("clauseTitle"),
                "clauseType": doc.get("clauseType"),
                "pageStart": doc.get("pageStart"),
                "pageEnd": doc.get("pageEnd"),
                "sourcePath": doc.get("sourcePath"),
                "text": doc.get("text"),

                # -----------------------------------------
                # EXPANDED HIERARCHICAL CONTEXT
                # -----------------------------------------

                "contextExpansion": expanded_context
            })

        return results