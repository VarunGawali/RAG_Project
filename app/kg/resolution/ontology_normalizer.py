"""
Pass 1 — ontology normalization (per clause extraction result).

Input : raw extraction dicts (LegalExtractionResult shape) for one contract.
Output: list[Node], list[Edge] with canonical labels + subtypes, role→edge,
        drifted/junk edges dropped (and counted), clause provenance denormalized.

Pure stdlib. See docs/kg_redesign_spec.md §6 Pass 1.
"""

from typing import Dict, List, Tuple

from app.kg.resolution import ontology as ont
from app.kg.resolution.model import Edge, Node, normalize_name

EXTRACTION_MODEL = "gpt-4.1-mini"
EXTRACTION_VERSION = "rebuild-v1"


def normalize_contract(
    contract_id: str,
    tenant_id: str,
    extraction_results: List[dict],
    extracted_at: str = "",
) -> Tuple[List[Node], List[Edge], Dict[str, int], Dict[str, int]]:
    """
    Returns (nodes, edges, dropped_edges, unmapped_labels).

    Node ids are taken from the extraction (already deterministic, e.g.
    'party:<contract>:<slug>'). De-fragmentation happens in Pass 2.
    """
    nodes: List[Node] = []
    edges: List[Edge] = []
    dropped: Dict[str, int] = {}
    unmapped: Dict[str, int] = {}

    for result in extraction_results:
        clause_id = result.get("source_clause_id")
        clause_title = result.get("source_clause_title")
        page_start = result.get("source_page_start")
        page_end = result.get("source_page_end")

        for ent in result.get("entities", []):
            raw_type = ent.get("type") or ""
            core, subtype, role = ont.map_entity_type(raw_type)
            if core is None:
                unmapped[raw_type] = unmapped.get(raw_type, 0) + 1
                core = "Concept"  # keep, don't discard — flagged in `unmapped`

            name = ent.get("name") or ""
            nodes.append(Node(
                kgId=ent.get("id"),
                label=core,
                subtype=subtype,
                name=name,
                normalizedName=normalize_name(name),
                tenantId=tenant_id,
                contractId=contract_id,
                sourceClauseId=clause_id,
                clauseTitle=clause_title,
                pageStart=page_start,
                pageEnd=page_end,
                evidenceQuote=ent.get("evidenceQuote"),
                roleNormalized=role,
                confidence=float(ent.get("confidence") or 0.0),
                extractionModel=EXTRACTION_MODEL,
                extractionVersion=EXTRACTION_VERSION,
                extractedAt=extracted_at or None,
            ))

        for rel in result.get("relationships", []):
            raw_label = rel.get("type") or ""
            label = ont.map_edge_label(raw_label)
            src = rel.get("source_id")
            dst = rel.get("target_id")

            if label is None:
                dropped[raw_label] = dropped.get(raw_label, 0) + 1
                continue
            # Drop edges that reference a clause vertex (we don't create those).
            if (src or "").startswith("clause:") or (dst or "").startswith("clause:"):
                dropped[f"{raw_label} (clause-anchored)"] = (
                    dropped.get(f"{raw_label} (clause-anchored)", 0) + 1
                )
                continue
            if not src or not dst:
                dropped[f"{raw_label} (missing endpoint)"] = (
                    dropped.get(f"{raw_label} (missing endpoint)", 0) + 1
                )
                continue

            edges.append(Edge(
                edgeId=f"{label}:{src}:{dst}",
                label=label,
                sourceId=src,
                targetId=dst,
                tenantId=tenant_id,
                contractId=contract_id,
                evidenceQuote=rel.get("evidenceQuote"),
                sourceClauseId=clause_id,
                confidence=float(rel.get("confidence") or 0.0),
            ))

    return nodes, edges, dropped, unmapped
