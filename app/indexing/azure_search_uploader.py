import json
import re
from pathlib import Path
from typing import Dict, Optional

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
)

from app import config


def _sanitize_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]", "_", value)


def load_kg_lookup(kg_path: Optional[str]) -> Dict[str, Dict]:
    """
    Load normalized KG JSON and build rawNodeId -> KG metadata lookup.

    Expected shape:
    {
      "nodes": [
        {
          "rawNodeId": "...",
          "kgId": "...",
          "parentKgId": "...",
          "nodeType": "...",
          "label": "Clause"
        }
      ]
    }
    """
    if not kg_path:
        return {}

    path = Path(kg_path)

    if not path.exists():
        raise FileNotFoundError(f"KG lookup file not found: {kg_path}")

    with open(path, "r", encoding="utf-8") as f:
        kg = json.load(f)

    lookup: Dict[str, Dict] = {}

    for node in kg.get("nodes", []):
        raw_node_id = node.get("rawNodeId")

        if not raw_node_id:
            continue

        lookup[raw_node_id] = {
            "kgId": node.get("kgId") or "",
            "parentKgId": node.get("parentKgId") or "",
            "nodeType": node.get("nodeType") or "",
            "graphLabel": node.get("label") or "",
        }

    return lookup


class AzureSearchIndexer:
    def __init__(
        self,
        endpoint: Optional[str] = None,
        admin_key: Optional[str] = None,
        index_name: Optional[str] = None,
    ):
        self.endpoint = endpoint or config.AZURE_SEARCH_ENDPOINT
        self.admin_key = admin_key or config.AZURE_SEARCH_ADMIN_KEY
        self.index_name = index_name or config.AZURE_SEARCH_INDEX

        if not self.endpoint:
            raise RuntimeError("AZURE_SEARCH_ENDPOINT missing")

        if not self.admin_key:
            raise RuntimeError("AZURE_SEARCH_ADMIN_KEY missing")

        self.credential = AzureKeyCredential(self.admin_key)

        self.index_client = SearchIndexClient(
            endpoint=self.endpoint,
            credential=self.credential,
        )

        self.search_client = SearchClient(
            endpoint=self.endpoint,
            index_name=self.index_name,
            credential=self.credential,
        )

    def delete_index_if_exists(self) -> None:
        try:
            self.index_client.delete_index(self.index_name)
            print(f"[Azure AI Search] Deleted index: {self.index_name}")
        except Exception as exc:
            print(f"[Azure AI Search] Delete skipped: {exc}")

    def create_or_update_index(self) -> None:
        fields = [
            SimpleField(
                name="id",
                type=SearchFieldDataType.String,
                key=True,
                filterable=True,
                sortable=True,
            ),
            SimpleField(
                name="contractId",
                type=SearchFieldDataType.String,
                filterable=True,
                facetable=True,
            ),
            SimpleField(
                name="documentId",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SimpleField(
                name="itemType",
                type=SearchFieldDataType.String,
                filterable=True,
                facetable=True,
            ),
            SimpleField(
                name="nodeId",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SimpleField(
                name="parentNodeId",
                type=SearchFieldDataType.String,
                filterable=True,
            ),

            # ------------------------------------------------
            # Graph bridge fields
            # ------------------------------------------------
            SimpleField(
                name="kgId",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SimpleField(
                name="parentKgId",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SimpleField(
                name="graphReady",
                type=SearchFieldDataType.Boolean,
                filterable=True,
                facetable=True,
            ),
            SearchableField(
                name="nodeType",
                type=SearchFieldDataType.String,
                searchable=True,
                filterable=True,
                facetable=True,
            ),
            SearchableField(
                name="graphLabel",
                type=SearchFieldDataType.String,
                searchable=True,
                filterable=True,
                facetable=True,
            ),

            SearchableField(
                name="title",
                type=SearchFieldDataType.String,
                searchable=True,
                filterable=True,
            ),
            SearchableField(
                name="sectionTitle",
                type=SearchFieldDataType.String,
                searchable=True,
                filterable=True,
                facetable=True,
            ),
            SearchableField(
                name="clauseTitle",
                type=SearchFieldDataType.String,
                searchable=True,
                filterable=True,
                facetable=True,
            ),
            SearchableField(
                name="clauseType",
                type=SearchFieldDataType.String,
                searchable=True,
                filterable=True,
                facetable=True,
            ),
            SearchableField(
                name="text",
                type=SearchFieldDataType.String,
                searchable=True,
            ),
            SimpleField(
                name="pageStart",
                type=SearchFieldDataType.Int32,
                filterable=True,
                sortable=True,
            ),
            SimpleField(
                name="pageEnd",
                type=SearchFieldDataType.Int32,
                filterable=True,
                sortable=True,
            ),
            SearchableField(
                name="sourcePath",
                type=SearchFieldDataType.String,
                searchable=True,
                filterable=True,
            ),
            SearchField(
                name="embedding",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=config.AZURE_SEARCH_VECTOR_DIMENSIONS,
                vector_search_profile_name="contract-vector-profile",
            ),
        ]

        vector_search = VectorSearch(
            algorithms=[
                HnswAlgorithmConfiguration(
                    name="contract-hnsw",
                )
            ],
            profiles=[
                VectorSearchProfile(
                    name="contract-vector-profile",
                    algorithm_configuration_name="contract-hnsw",
                )
            ],
        )

        semantic_search = SemanticSearch(
            configurations=[
                SemanticConfiguration(
                    name="contract-semantic-config",
                    prioritized_fields=SemanticPrioritizedFields(
                        title_field=SemanticField(field_name="title"),
                        content_fields=[
                            SemanticField(field_name="text"),
                            SemanticField(field_name="sourcePath"),
                        ],
                        keywords_fields=[
                            SemanticField(field_name="sectionTitle"),
                            SemanticField(field_name="clauseTitle"),
                            SemanticField(field_name="clauseType"),
                            SemanticField(field_name="nodeType"),
                            SemanticField(field_name="graphLabel"),
                        ],
                    ),
                )
            ]
        )

        index = SearchIndex(
            name=self.index_name,
            fields=fields,
            vector_search=vector_search,
            semantic_search=semantic_search,
        )

        self.index_client.create_or_update_index(index)

        print(f"[Azure AI Search] Index created/updated: {self.index_name}")

    def _prepare_doc(
        self,
        d: Dict,
        kg_lookup: Optional[Dict[str, Dict]] = None,
    ) -> Dict:
        kg_lookup = kg_lookup or {}

        raw_node_id = d.get("nodeId") or ""
        kg_meta = kg_lookup.get(raw_node_id, {})

        kg_id = d.get("kgId") or kg_meta.get("kgId") or ""
        parent_kg_id = d.get("parentKgId") or kg_meta.get("parentKgId") or ""
        node_type = d.get("nodeType") or kg_meta.get("nodeType") or ""
        graph_label = d.get("graphLabel") or kg_meta.get("graphLabel") or ""

        prepared = {
            "id": _sanitize_key(str(d.get("id"))),
            "contractId": d.get("contractId") or "",
            "documentId": d.get("documentId") or "",
            "itemType": d.get("itemType") or "",
            "nodeId": raw_node_id,
            "parentNodeId": d.get("parentNodeId") or "",

            # Graph bridge fields
            "kgId": kg_id,
            "parentKgId": parent_kg_id,
            "graphReady": bool(kg_id),
            "nodeType": node_type,
            "graphLabel": graph_label,

            "title": d.get("title") or "",
            "sectionTitle": d.get("sectionTitle") or "",
            "clauseTitle": d.get("clauseTitle") or "",
            "clauseType": d.get("clauseType") or "",
            "text": d.get("text") or "",
            "pageStart": d.get("pageStart") or 0,
            "pageEnd": d.get("pageEnd") or d.get("pageStart") or 0,
            "sourcePath": d.get("sourcePath") or "",
            "embedding": d.get("embedding") or [],
        }

        return prepared

    def upload_documents(
        self,
        docs: list,
        batch_size: int = 500,
        kg_lookup: Optional[Dict[str, Dict]] = None,
    ) -> int:
        """
        Upload an already-loaded list of document dicts to Azure AI Search.
        Preferred over upload_documents_from_file for in-memory pipelines.
        """
        kg_lookup = kg_lookup or {}

        prepared_docs = [
            self._prepare_doc(d, kg_lookup=kg_lookup)
            for d in docs
        ]

        graph_ready_count = sum(1 for d in prepared_docs if d.get("graphReady"))
        print(
            f"[Azure AI Search] Graph-ready docs: "
            f"{graph_ready_count}/{len(prepared_docs)}"
        )

        total = 0
        for i in range(0, len(prepared_docs), batch_size):
            batch = prepared_docs[i : i + batch_size]
            result = self.search_client.upload_documents(batch)
            failed = [r for r in result if not r.succeeded]
            if failed:
                print("[Azure AI Search] Upload failures:")
                for f in failed[:10]:
                    print(f)
                raise RuntimeError("Some documents failed to upload")
            total += len(batch)
            print(f"[Azure AI Search] Uploaded {total}/{len(prepared_docs)}")

        return total

    def upload_documents_from_file(
        self,
        corpus_path: str,
        batch_size: int = 500,
        kg_path: Optional[str] = None,
    ) -> int:
        path = Path(corpus_path)

        if not path.exists():
            raise FileNotFoundError(corpus_path)

        with open(path, "r", encoding="utf-8") as f:
            docs = json.load(f)

        kg_lookup = load_kg_lookup(kg_path)

        if kg_lookup:
            print(
                f"[Azure AI Search] Loaded KG lookup with "
                f"{len(kg_lookup)} rawNodeId mappings"
            )

        prepared_docs = [
            self._prepare_doc(d, kg_lookup=kg_lookup)
            for d in docs
        ]

        graph_ready_count = sum(
            1 for d in prepared_docs
            if d.get("graphReady")
        )

        print(
            f"[Azure AI Search] Graph-ready docs: "
            f"{graph_ready_count}/{len(prepared_docs)}"
        )

        total = 0

        for i in range(0, len(prepared_docs), batch_size):
            batch = prepared_docs[i:i + batch_size]
            result = self.search_client.upload_documents(batch)

            failed = [
                r for r in result
                if not r.succeeded
            ]

            if failed:
                print("[Azure AI Search] Upload failures:")
                for f in failed[:10]:
                    print(f)
                raise RuntimeError("Some documents failed to upload")

            total += len(batch)
            print(f"[Azure AI Search] Uploaded {total}/{len(prepared_docs)}")

        return total