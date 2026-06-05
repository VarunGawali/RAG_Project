"""
Semantic retriever for TreeRAG.

Loads the contract tree from Azure Blob Storage (not local disk),
uses Azure AI Search for vector retrieval, then expands context
hierarchically using the in-memory tree indices.

Tree cache: module-level dict keyed by contract_id so repeated
queries for the same contract don't re-download from Blob.
"""

import logging
from typing import Any, Dict, List, Optional

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery

from app import config
from app.embedding.embedding_client import EmbeddingClient

logger = logging.getLogger(__name__)

# In-memory tree cache: contract_id → tree dict
# Populated lazily on first access per contract.
_TREE_CACHE: Dict[str, Dict] = {}


def _load_tree_from_blob(contract_id: str) -> Optional[Dict]:
    """Download tree.json for a contract from Azure Blob Storage."""
    try:
        from app.storage.blob_artifact_store import BlobArtifactStore
        store = BlobArtifactStore()
        tree = store.get_tree(contract_id)
        if tree is None:
            logger.warning("tree.json not found in Blob for contract '%s'.", contract_id)
        return tree
    except Exception as exc:
        logger.error("Failed to load tree from Blob for '%s': %s", contract_id, exc)
        return None


class SemanticRetriever:
    """
    Retrieves semantically relevant chunks from Azure AI Search and
    expands each result with hierarchical tree context (parent, siblings,
    children) loaded from Azure Blob Storage.
    """

    def __init__(
        self,
        contract_id: Optional[str] = None,
        tree_data: Optional[Dict] = None,
    ):
        """
        Parameters
        ----------
        contract_id : str, optional
            If provided, tree.json is loaded from Blob (with caching).
        tree_data : dict, optional
            Pass a pre-loaded tree dict directly (skips Blob lookup).
            Useful for tests or when the caller already has the tree.
        """
        self.node_lookup: Dict[str, Dict] = {}
        self.children_lookup: Dict[str, List] = {}

        # Resolve tree data
        tree: Optional[Dict] = tree_data
        if tree is None and contract_id:
            if contract_id in _TREE_CACHE:
                tree = _TREE_CACHE[contract_id]
            else:
                tree = _load_tree_from_blob(contract_id)
                if tree is not None:
                    _TREE_CACHE[contract_id] = tree

        if tree is not None:
            self._build_tree_indices(tree)
            logger.info(
                "TreeRAG: loaded %d nodes for contract '%s'.",
                len(self.node_lookup), contract_id or "(direct)",
            )
        else:
            logger.info(
                "TreeRAG: no tree available for contract '%s' — "
                "context expansion will be skipped.",
                contract_id,
            )

        # Azure AI Search client
        self._search_client = SearchClient(
            endpoint=config.AZURE_SEARCH_ENDPOINT,
            index_name=config.AZURE_SEARCH_INDEX,
            credential=AzureKeyCredential(config.AZURE_SEARCH_ADMIN_KEY),
        )
        self._embedder = EmbeddingClient()

    # ------------------------------------------------------------------
    # Tree index building
    # ------------------------------------------------------------------

    def _build_tree_indices(self, node: Dict) -> None:
        node_id = node.get("nodeId")
        if node_id:
            self.node_lookup[node_id] = node
        children = node.get("children", [])
        self.children_lookup[node_id] = children
        for child in children:
            self._build_tree_indices(child)

    # ------------------------------------------------------------------
    # Hierarchical context expansion
    # ------------------------------------------------------------------

    def expand_context(self, node_id: str) -> List[Dict]:
        """
        Return the current node plus its parent (if not document-root),
        siblings, and immediate children.
        """
        if not node_id or node_id not in self.node_lookup:
            return []

        expanded: List[Dict] = []
        current = self.node_lookup[node_id]
        expanded.append(current)

        parent_id = current.get("parentNodeId")

        # Add parent (skip document root — too broad)
        if parent_id:
            parent = self.node_lookup.get(parent_id)
            if parent and parent.get("nodeType") != "document":
                expanded.append(parent)

        # Add siblings
        if parent_id:
            for sibling in self.children_lookup.get(parent_id, []):
                if sibling.get("nodeId") != node_id:
                    expanded.append(sibling)

        # Add children
        expanded.extend(self.children_lookup.get(node_id, []))

        return expanded

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        contract_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Vector-search Azure AI Search, then expand each hit with tree context.

        Returns a list of result dicts; each includes a 'contextExpansion'
        list of tree nodes for use in prompt building.
        """
        query_embedding = self._embedder.embed(query)

        vector_query = VectorizedQuery(
            vector=query_embedding,
            k_nearest_neighbors=top_k,
            fields="embedding",
        )

        filter_expr = None
        if contract_id:
            safe = contract_id.replace("'", "''")
            filter_expr = f"contractId eq '{safe}'"

        search_results = self._search_client.search(
            search_text=query,
            vector_queries=[vector_query],
            top=top_k,
            filter=filter_expr,
            select=[
                "id", "contractId", "nodeId", "parentNodeId",
                "title", "sectionTitle", "clauseTitle", "clauseType",
                "pageStart", "pageEnd", "sourcePath", "text",
                "kgId", "graphReady",
            ],
        )

        results = []
        for hit in search_results:
            node_id = hit.get("nodeId")
            results.append({
                "score":            hit.get("@search.score"),
                "contractId":       hit.get("contractId"),
                "nodeId":           node_id,
                "parentNodeId":     hit.get("parentNodeId"),
                "title":            hit.get("title"),
                "sectionTitle":     hit.get("sectionTitle"),
                "clauseTitle":      hit.get("clauseTitle"),
                "clauseType":       hit.get("clauseType"),
                "pageStart":        hit.get("pageStart"),
                "pageEnd":          hit.get("pageEnd"),
                "sourcePath":       hit.get("sourcePath"),
                "text":             hit.get("text"),
                "kgId":             hit.get("kgId"),
                "contextExpansion": self.expand_context(node_id) if node_id else [],
            })

        return results
