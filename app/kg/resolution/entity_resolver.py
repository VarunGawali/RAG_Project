"""
Pass 2 — per-contract entity resolution.

  - dedup mentions sharing a kgId (same id from multiple clauses)
  - classify Party / GovernmentalAuthority mentions as named | role | concept
  - de-fragment: merge Party / GovernmentalAuthority nodes that share
    (contractId, label, normalizedName) into a single canonical-per-contract node
  - rewrite all edges through the id remap; dedup edges

Pure stdlib. See docs/kg_redesign_spec.md §6 Pass 2.
"""

from typing import Dict, List, Tuple

from app.kg.resolution import ontology as ont
from app.kg.resolution.model import Edge, Node, slug

# Labels whose mentions are merged by normalized name (the fragmentation fix).
# Fact nodes (Obligation/Right/Event/...) are NOT merged by name — they're
# distinct duties/events; they dedup only by identical kgId.
MERGE_BY_NAME_LABELS = {"Party", "GovernmentalAuthority"}


def _merge_nodes(group: List[Node], target_id: str) -> Node:
    """Collapse a group of nodes into one (highest-confidence base)."""
    base = max(group, key=lambda x: x.confidence)
    merged = Node(
        kgId=target_id,
        label=base.label,
        subtype=base.subtype,
        name=base.name,
        normalizedName=base.normalizedName,
        tenantId=base.tenantId,
        contractId=base.contractId,
        sourceClauseId=base.sourceClauseId,
        clauseTitle=base.clauseTitle,
        pageStart=base.pageStart,
        pageEnd=base.pageEnd,
        sourcePath=base.sourcePath,
        evidenceQuote=base.evidenceQuote,
        entityClass=base.entityClass,
        roleNormalized=base.roleNormalized,
        confidence=base.confidence,
        extractionModel=base.extractionModel,
        extractionVersion=base.extractionVersion,
        extractedAt=base.extractedAt,
    )
    seen = set()
    for n in group:
        for src in (n.mergedFrom or [n.kgId]):
            if src != target_id and src not in seen:
                seen.add(src)
                merged.mergedFrom.append(src)
        # fill any missing citation fields
        merged.clauseTitle = merged.clauseTitle or n.clauseTitle
        merged.pageStart = merged.pageStart if merged.pageStart is not None else n.pageStart
        merged.pageEnd = merged.pageEnd if merged.pageEnd is not None else n.pageEnd
        merged.roleNormalized = merged.roleNormalized or n.roleNormalized
    return merged


def resolve_contract(
    nodes: List[Node],
    edges: List[Edge],
) -> Tuple[List[Node], List[Edge]]:
    """De-fragment + classify within one contract; remap edges."""
    # 1. classify Party / GovernmentalAuthority
    for n in nodes:
        if n.label in ("Party", "GovernmentalAuthority"):
            n.entityClass = ont.classify_party(n.normalizedName)

    # 2. assign each node a target id (merge key)
    id_map: Dict[str, str] = {}
    groups: Dict[str, List[Node]] = {}
    for n in nodes:
        if n.label in MERGE_BY_NAME_LABELS and n.normalizedName:
            target = f"{n.label.lower()}:{n.contractId}:{slug(n.normalizedName)}"
        else:
            target = n.kgId  # dedup by identical id only
        id_map[n.kgId] = target
        groups.setdefault(target, []).append(n)

    merged_nodes = {tid: _merge_nodes(grp, tid) for tid, grp in groups.items()}

    # 3. remap + dedup edges (drop self-loops created by merging)
    out_edges: Dict[str, Edge] = {}
    for e in edges:
        src = id_map.get(e.sourceId, e.sourceId)
        dst = id_map.get(e.targetId, e.targetId)
        if src == dst:
            continue
        eid = f"{e.label}:{src}:{dst}"
        if eid in out_edges:
            # keep the higher-confidence evidence
            if e.confidence > out_edges[eid].confidence:
                out_edges[eid].confidence = e.confidence
                out_edges[eid].evidenceQuote = e.evidenceQuote
            continue
        out_edges[eid] = Edge(
            edgeId=eid, label=e.label, sourceId=src, targetId=dst,
            tenantId=e.tenantId, contractId=e.contractId, role=e.role,
            evidenceQuote=e.evidenceQuote, sourceClauseId=e.sourceClauseId,
            confidence=e.confidence,
        )

    return list(merged_nodes.values()), list(out_edges.values())
