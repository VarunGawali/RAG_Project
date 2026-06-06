import json
import time
from typing import Dict, Any, Optional

from gremlin_python.driver import client, serializer

from app import config
from app.kg.models import NormalizedContract, LegalExtractionResult


MAX_TEXT_PREVIEW_CHARS = 1200
MAX_STRING_PROPERTY_CHARS = 4000
MAX_RETRIES = 4


def clean_value(value):
    """
    Convert values into Cosmos Gremlin-safe primitive values.
    Lists/dicts are converted to JSON strings and trimmed.
    """
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        if len(value) > MAX_STRING_PROPERTY_CHARS:
            return value[:MAX_STRING_PROPERTY_CHARS] + "...[truncated]"
        return value

    if isinstance(value, list):
        text = json.dumps(value, ensure_ascii=False)
        if len(text) > MAX_STRING_PROPERTY_CHARS:
            return text[:MAX_STRING_PROPERTY_CHARS] + "...[truncated]"
        return text

    if isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False)
        if len(text) > MAX_STRING_PROPERTY_CHARS:
            return text[:MAX_STRING_PROPERTY_CHARS] + "...[truncated]"
        return text

    text = str(value)
    if len(text) > MAX_STRING_PROPERTY_CHARS:
        return text[:MAX_STRING_PROPERTY_CHARS] + "...[truncated]"
    return text


class GremlinWriter:
    def __init__(self):
        self.client = None
        self._connect()

    def _connect(self):
        self.client = client.Client(
            config.GREMLIN_ENDPOINT,
            "g",
            username=config.GREMLIN_USERNAME,
            password=config.GREMLIN_PASSWORD,
            message_serializer=serializer.GraphSONSerializersV2d0(),
        )

    def close(self):
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass

    def reconnect(self):
        self.close()
        time.sleep(1)
        self._connect()

    def submit(self, query: str, bindings: Optional[Dict[str, Any]] = None):
        """
        Submit query with manual retry and reconnect.

        Tenacity retries alone do not recreate the closed WebSocket client.
        """
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result_set = self.client.submit(query, bindings or {})
                return result_set.all().result()

            except Exception as e:
                last_error = e
                print(f"Gremlin query failed attempt {attempt}/{MAX_RETRIES}: {type(e).__name__}: {e}")

                if attempt < MAX_RETRIES:
                    self.reconnect()
                    time.sleep(min(2 ** attempt, 8))

        raise last_error

    def upsert_vertex(
        self,
        label: str,
        vertex_id: str,
        pk: str,
        properties: Dict[str, Any],
    ):
        """
        Upsert vertex in a single query — all properties chained inline.
        One RU round-trip instead of N+1.
        """
        clean_props = {
            k: clean_value(v)
            for k, v in properties.items()
            if k not in {"id", "label"} and clean_value(v) not in (None, "")
        }

        # Build chained .property() calls as part of one traversal
        prop_chain = "".join(
            f".property(p{i}k, p{i}v)" for i in range(len(clean_props))
        )
        query = f"""
        g.V(vid).fold().
          coalesce(
            unfold(),
            addV(vlabel).property('id', vid).property('pk', pk)
          ){prop_chain}
        """

        bindings = {"vid": vertex_id, "vlabel": label, "pk": pk}
        for i, (k, v) in enumerate(clean_props.items()):
            bindings[f"p{i}k"] = k
            bindings[f"p{i}v"] = v

        self.submit(query, bindings)

    def upsert_edge(
        self,
        source_id: str,
        target_id: str,
        edge_label: str,
        properties: Optional[Dict[str, Any]] = None,
    ):
        """
        Upsert edge between two existing vertices.
        """
        properties = properties or {}

        clean_props = {
            k: clean_value(v)
            for k, v in properties.items()
            if clean_value(v) not in (None, "")
        }

        prop_chain = "".join(
            f".property(p{i}k, p{i}v)" for i in range(len(clean_props))
        )
        query = f"""
        g.V(source_id).as('s').
          V(target_id).as('t').
          coalesce(
            __.outE(edge_label).where(inV().hasId(target_id)),
            __.addE(edge_label).from('s').to('t')
          ){prop_chain}
        """

        bindings = {
            "source_id": source_id,
            "target_id": target_id,
            "edge_label": edge_label,
        }
        for i, (k, v) in enumerate(clean_props.items()):
            bindings[f"p{i}k"] = k
            bindings[f"p{i}v"] = v

        self.submit(query, bindings)

    def write_structural_graph(self, normalized: NormalizedContract):
        """
        Write deterministic structural KG.

        Important:
        Full node text is NOT stored in Gremlin.
        Gremlin stores textPreview + textLength only.
        Full text remains in tree JSON / Azure AI Search.
        """
        print("Writing structural vertices...")

        total_nodes = len(normalized.nodes)

        for idx, node in enumerate(normalized.nodes, start=1):
            full_text = node.text or ""

            props = {
                "kgId": node.kgId,
                "rawNodeId": node.rawNodeId,
                "tenantId": node.tenantId,
                "contractId": node.contractId,
                "nodeType": node.nodeType,
                "title": node.title,
                "textPreview": full_text[:MAX_TEXT_PREVIEW_CHARS],
                "textLength": len(full_text),
                "sectionNumber": node.sectionNumber,
                "pageStart": node.pageStart,
                "pageEnd": node.pageEnd,
                "sourcePath": node.sourcePath,
                "parentKgId": node.parentKgId,
                "childrenCount": len(node.childrenKgIds or []),
                "siblingCount": len(node.siblingKgIds or []),
                "clauseTypeHint": node.clauseTypeHint,
                "extractionReady": node.extractionReady,
                "rawItemType": node.properties.get("itemType"),
                "rawDocumentId": node.properties.get("documentId"),
                "rawParentNodeId": node.properties.get("parentNodeId"),
            }

            self.upsert_vertex(
                label=node.label,
                vertex_id=node.kgId,
                pk=node.tenantId,
                properties=props,
            )

            if idx % 25 == 0 or idx == total_nodes:
                print(f"  Vertices written: {idx}/{total_nodes}")

        print("Writing structural edges...")

        total_edges = len(normalized.edges)

        for idx, edge in enumerate(normalized.edges, start=1):
            self.upsert_edge(
                source_id=edge.sourceKgId,
                target_id=edge.targetKgId,
                edge_label=edge.label,
                properties={
                    "edgeId": edge.edgeId,
                    "tenantId": edge.tenantId,
                    "edgeType": edge.properties.get("edgeType", "structural"),
                },
            )

            if idx % 50 == 0 or idx == total_edges:
                print(f"  Edges written: {idx}/{total_edges}")

        print("Structural graph written successfully.")

    def write_legal_extraction(
        self,
        extraction: LegalExtractionResult,
        tenant_id: str,
        contract_id: str,
    ):
        """
        Later step: write LLM-extracted legal semantic graph.
        """
        source_clause_id = extraction.source_clause_id

        for entity in extraction.entities:
            props = {
                "kgId": entity.id,
                "tenantId": tenant_id,
                "contractId": contract_id,
                "nodeType": "legal_entity",
                "legalType": entity.type,
                "name": entity.name,
                "confidence": entity.confidence,
                "evidenceQuote": entity.evidenceQuote,
                "sourceClauseId": source_clause_id,
                **entity.properties,
            }

            self.upsert_vertex(
                label=entity.type,
                vertex_id=entity.id,
                pk=tenant_id,
                properties=props,
            )

            self.upsert_edge(
                source_id=source_clause_id,
                target_id=entity.id,
                edge_label="EXTRACTED_ENTITY",
                properties={
                    "tenantId": tenant_id,
                    "confidence": entity.confidence,
                    "evidenceQuote": entity.evidenceQuote,
                },
            )

        for rel in extraction.relationships:
            self.upsert_edge(
                source_id=rel.source_id,
                target_id=rel.target_id,
                edge_label=rel.type,
                properties={
                    "tenantId": tenant_id,
                    "confidence": rel.confidence,
                    "evidenceQuote": rel.evidenceQuote,
                    **rel.properties,
                },
            )
