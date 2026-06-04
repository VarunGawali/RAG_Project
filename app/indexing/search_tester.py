from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery

from app import config
from app.embedding.embedding_client import EmbeddingClient

def roman_to_int(value: str):
    roman = {
        "I": 1,
        "II": 2,
        "III": 3,
        "IV": 4,
        "V": 5,
        "VI": 6,
        "VII": 7,
        "VIII": 8,
        "IX": 9,
        "X": 10,
        "XI": 11,
        "XII": 12,
        "XIII": 13,
        "XIV": 14,
        "XV": 15,
        "XVI": 16,
        "XVII": 17,
        "XVIII": 18,
        "XIX": 19,
        "XX": 20,
        "XXI": 21,
        "XXII": 22,
        "XXIII": 23,
        "XXIV": 24,
        "XXV": 25,
        "XXVI": 26,
        "XXVII": 27,
        "XXVIII": 28,
        "XXIX": 29,
        "XXX": 30,
        "XXXI": 31,
        "XXXII": 32,
        "XXXIII": 33,
        "XXXIV": 34,
    }

    return roman.get(value.upper())


def is_doc_in_article_scope(doc: dict, article_identifier: str) -> bool:
    """
    Post-filter docs for a requested article.

    This guards against parser/tree cases where sectionTitle may say ARTICLE XII
    but the title/sourcePath actually belongs to a neighboring article.
    """

    article_identifier = article_identifier.upper()
    article_num = roman_to_int(article_identifier)

    title = doc.get("title") or ""
    source_path = doc.get("sourcePath") or ""
    graph_label = doc.get("graphLabel") or ""
    node_type = doc.get("nodeType") or ""

    article_title = f"ARTICLE {article_identifier}"

    # Keep the article heading node itself.
    if title.strip().upper() == article_title:
        return True

    # Keep section node.
    if graph_label == "Section" or node_type == "section":
        return title.strip().upper() == article_title

    # For Article XII, keep clauses starting with 12.
    if article_num is not None:
        prefix = f"{article_num}."

        if title.strip().startswith(prefix):
            return True

        if f"> {article_title} > {prefix}" in source_path:
            return True

    return False


class AzureSearchTester:
    def __init__(self):
        self.client = SearchClient(
            endpoint=config.AZURE_SEARCH_ENDPOINT,
            index_name=config.AZURE_SEARCH_INDEX,
            credential=AzureKeyCredential(config.AZURE_SEARCH_ADMIN_KEY),
        )
        self.embedder = EmbeddingClient()

    def hybrid_search(
        self,
        query: str,
        contract_id: str = None,
        top: int = 5,
        graph_ready_only: bool = False,
    ):
        """
        Hybrid keyword + vector search over Azure AI Search.

        Used for:
        - normal semantic search
        - hybrid GraphRAG entry-point search
        """

        query_vector = self.embedder.embed(query)

        vector_query = VectorizedQuery(
            vector=query_vector,
            k_nearest_neighbors=30,
            fields="embedding",
        )

        filters = []

        if contract_id:
            safe_contract_id = contract_id.replace("'", "''")
            filters.append(f"contractId eq '{safe_contract_id}'")

        if graph_ready_only:
            filters.append("graphReady eq true")

        filter_expr = " and ".join(filters) if filters else None

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

                # Graph bridge fields
                "kgId",
                "parentKgId",
                "graphReady",
                "nodeType",
                "graphLabel",

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

    def retrieve_structural_scope(
        self,
        structure_type: str,
        identifier: str,
        contract_id: str = None,
        top: int = 100,
    ):
        """
        Generic structural retrieval.

        Supports:
        - Article retrieval using sectionTitle filter + post-filter
        Example:
            structure_type='Article', identifier='XII'
            -> retrieves ARTICLE XII and its 12.x clauses

        Later this can be extended for:
        - Section 3.1
        - Clause 12.4
        - Appendix A
        - Exhibit B
        """

        normalized_type = (structure_type or "").strip().lower()
        normalized_identifier = (identifier or "").strip().upper()

        if not normalized_type or not normalized_identifier:
            return []

        filters = []

        if normalized_type in ["article", "section"]:
            section_title = f"ARTICLE {normalized_identifier}"
            safe_section_title = section_title.replace("'", "''")
            filters.append(f"sectionTitle eq '{safe_section_title}'")

        elif normalized_type == "clause":
            safe_identifier = normalized_identifier.replace("'", "''")
            filters.append(f"search.ismatch('{safe_identifier}', 'clauseTitle')")

        else:
            raise ValueError(
                f"Unsupported structure_type: {structure_type}. "
                "Supported: Article, Section, Clause"
            )

        if contract_id:
            safe_contract_id = contract_id.replace("'", "''")
            filters.append(f"contractId eq '{safe_contract_id}'")

        filter_expr = " and ".join(filters)

        results = self.client.search(
            search_text="*",
            filter=filter_expr,
            top=top,
            order_by=["pageStart asc"],
            select=[
                "id",
                "contractId",
                "documentId",
                "itemType",
                "nodeId",
                "parentNodeId",

                # Graph bridge fields
                "kgId",
                "parentKgId",
                "graphReady",
                "nodeType",
                "graphLabel",

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

        docs = [dict(r) for r in results]

        # Post-filter article scope to prevent parser bleed-over,
        # e.g. title "13.1 ..." still having sectionTitle "ARTICLE XII".
        if normalized_type in ["article", "section"]:
            docs = [
                d for d in docs
                if is_doc_in_article_scope(d, normalized_identifier)
            ]

        docs.sort(
            key=lambda d: (
                d.get("pageStart") or 0,
                d.get("title") or "",
            )
        )

        return docs