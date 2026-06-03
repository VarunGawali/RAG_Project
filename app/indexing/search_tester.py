import json

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery

from app import config
from app.embedding.embedding_client import EmbeddingClient


class AzureSearchTester:
    def __init__(self):
        self.client = SearchClient(
            endpoint=config.AZURE_SEARCH_ENDPOINT,
            index_name=config.AZURE_SEARCH_INDEX,
            credential=AzureKeyCredential(config.AZURE_SEARCH_ADMIN_KEY),
        )
        self.embedder = EmbeddingClient()

    def hybrid_search(self, query: str, contract_id: str = None, top: int = 5):
        query_vector = self.embedder.embed(query)

        vector_query = VectorizedQuery(
            vector=query_vector,
            k_nearest_neighbors=30,
            fields="embedding",
        )

        filter_expr = None
        if contract_id:
            safe_contract_id = contract_id.replace("'", "''")
            filter_expr = f"contractId eq '{safe_contract_id}'"

        results = self.client.search(
            search_text=query,
            vector_queries=[vector_query],
            filter=filter_expr,
            top=top,
            select=[
                "id",
                "contractId",
                "documentId",
                "itemType",
                "nodeId",
                "parentNodeId",
                "title",
                "sectionTitle",
                "clauseTitle",
                "clauseType",
                "text",
                "pageStart",
                "pageEnd",
                "sourcePath",
            ],
        )

        return [dict(r) for r in results]