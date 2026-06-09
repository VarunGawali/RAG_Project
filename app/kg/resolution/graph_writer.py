"""
Convert the ResolvedGraph dataclasses into Gremlin vertex/edge property dicts,
and write them via GremlinWriter. Kept separate from the orchestration script
so the conversion is unit-testable without Gremlin.
"""

from typing import Dict, List, Tuple

from app.kg.resolution.model import CanonicalEntity, Edge, Node, ResolvedGraph


def node_props(n: Node) -> dict:
    """Vertex properties for a Tier-1 mention node. 'id'/'label' set by writer."""
    props = {
        "kgId": n.kgId,
        "nodeType": "legal_entity",
        "legalType": n.label,          # keep queryable type alongside vertex label
        "subtype": n.subtype,
        "name": n.name,
        "normalizedName": n.normalizedName,
        "tenantId": n.tenantId,
        "contractId": n.contractId,
        "sourceClauseId": n.sourceClauseId,
        "clauseTitle": n.clauseTitle,
        "sectionTitle": n.sectionTitle,
        "pageStart": n.pageStart,
        "pageEnd": n.pageEnd,
        "sourcePath": n.sourcePath,
        "evidenceQuote": n.evidenceQuote,
        "entityClass": n.entityClass,
        "roleNormalized": n.roleNormalized,
        "canonicalId": n.canonicalId,
        "confidence": n.confidence,
        "extractionModel": n.extractionModel,
        "extractionVersion": n.extractionVersion,
        "extractedAt": n.extractedAt,
        "searchDocId": n.searchDocId,
    }
    return {k: v for k, v in props.items() if v is not None}


def canonical_props(c: CanonicalEntity) -> dict:
    """Vertex properties for a Tier-2 CanonicalEntity (aliases/contractIds → JSON via clean_value)."""
    props = {
        "kgId": c.id,
        "nodeType": "canonical_entity",
        "canonicalName": c.canonicalName,
        "entityClass": c.entityClass,
        "aliases": c.aliases,
        "contractIds": c.contractIds,
        "mentionCount": c.mentionCount,
        "searchDocId": c.searchDocId,
    }
    return {k: v for k, v in props.items() if v is not None}


def edge_props(e: Edge) -> dict:
    props = {
        "edgeId": e.edgeId,
        "tenantId": e.tenantId,
        "contractId": e.contractId,
        "role": e.role,
        "evidenceQuote": e.evidenceQuote,
        "sourceClauseId": e.sourceClauseId,
        "confidence": e.confidence,
    }
    return {k: v for k, v in props.items() if v is not None}


def write_resolved_graph(writer, graph: ResolvedGraph, tenant_id: str,
                         delay: float = 0.0, log=print) -> dict:
    """
    Write a ResolvedGraph to Gremlin via an existing GremlinWriter.
    Idempotent (deterministic ids). Used by both the rebuild script and the
    ingestion worker. Returns a small summary dict.
    """
    import time
    sem_edges, res_edges, skipped = validate_edges(graph)

    for n in graph.nodes.values():
        writer.upsert_vertex(label=n.label, vertex_id=n.kgId, pk=n.tenantId,
                             properties=node_props(n))
        if delay:
            time.sleep(delay)

    for c in graph.canonicals.values():
        writer.upsert_vertex(label="CanonicalEntity", vertex_id=c.id, pk=tenant_id,
                             properties=canonical_props(c))
        if delay:
            time.sleep(delay)

    for e in sem_edges:
        writer.upsert_edge(source_id=e.sourceId, target_id=e.targetId,
                           edge_label=e.label, properties=edge_props(e))
        if delay:
            time.sleep(delay)

    for e in res_edges:
        writer.upsert_edge(source_id=e.sourceId, target_id=e.targetId,
                           edge_label="RESOLVED_AS", properties=edge_props(e))
        if delay:
            time.sleep(delay)

    summary = {
        "mention_vertices": len(graph.nodes),
        "canonical_vertices": len(graph.canonicals),
        "semantic_edges": len(sem_edges),
        "resolved_as_edges": len(res_edges),
        "skipped_edges": sum(skipped.values()),
    }
    if log:
        log(f"  wrote {summary}")
    return summary


def validate_edges(graph: ResolvedGraph) -> Tuple[List[Edge], List[Edge], Dict[str, int]]:
    """
    Keep only edges whose endpoints exist as written vertices.
      - semantic edges: both endpoints in mention nodes
      - RESOLVED_AS  : source in mention nodes, target in canonicals
    Returns (valid_semantic, valid_resolved_as, skipped_counts).
    """
    node_ids = set(graph.nodes.keys())
    canon_ids = set(graph.canonicals.keys())
    skipped: Dict[str, int] = {}

    valid_sem: List[Edge] = []
    for e in graph.edges.values():
        if e.sourceId in node_ids and e.targetId in node_ids:
            valid_sem.append(e)
        else:
            skipped[f"{e.label} (orphan endpoint)"] = skipped.get(f"{e.label} (orphan endpoint)", 0) + 1

    valid_res: List[Edge] = []
    for e in graph.resolved_as:
        if e.sourceId in node_ids and e.targetId in canon_ids:
            valid_res.append(e)
        else:
            skipped["RESOLVED_AS (orphan endpoint)"] = skipped.get("RESOLVED_AS (orphan endpoint)", 0) + 1

    return valid_sem, valid_res, skipped
