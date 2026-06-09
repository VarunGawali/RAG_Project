"""
Resolution pipeline orchestrator (Pass 1 → 2 → 3), pure stdlib.

Reads saved extraction JSONs from a directory and returns a ResolvedGraph.
No Gremlin / Azure dependencies — safe to run and audit locally.
"""

import json
from pathlib import Path
from typing import List, Optional

from app.kg.resolution.model import ResolvedGraph
from app.kg.resolution.ontology_normalizer import normalize_contract
from app.kg.resolution.entity_resolver import resolve_contract
from app.kg.resolution.canonicalizer import canonicalize

# Inputs to skip (junk / empty / non-contract).
SKIP_STEMS = {
    "ITEM-Attachment-001-8b61c09bae2e4baf9088744b1bb5d2b5_1",
}


def _contract_id_from_file(path: Path) -> str:
    return path.stem.replace("_legal_extractions", "")


def resolve_one_contract(
    contract_id: str,
    tenant_id: str,
    extraction_results: List[dict],
) -> ResolvedGraph:
    """
    Run Pass 1→2→3 for a SINGLE contract's extraction results (in memory).
    Used by the ingestion worker. Canonical ids are deterministic, so writing
    the result idempotently merges into any existing canonical entities.
    """
    graph = ResolvedGraph()
    nodes, edges, dropped, unmapped = normalize_contract(
        contract_id=contract_id, tenant_id=tenant_id, extraction_results=extraction_results,
    )
    graph.dropped_edges = dropped
    graph.unmapped_labels = unmapped

    nodes, edges = resolve_contract(nodes, edges)
    for n in nodes:
        graph.nodes[n.kgId] = n
    for e in edges:
        graph.edges[e.edgeId] = e

    canonicals, resolved_as = canonicalize(list(graph.nodes.values()))
    graph.canonicals = canonicals
    graph.resolved_as = resolved_as
    return graph


def run_pipeline(
    extractions_dir: str,
    tenant_id: str = "default",
    only_contracts: Optional[List[str]] = None,
) -> ResolvedGraph:
    graph = ResolvedGraph()
    files = sorted(Path(extractions_dir).glob("*_legal_extractions.json"))

    for f in files:
        contract_id = _contract_id_from_file(f)
        if contract_id in SKIP_STEMS:
            continue
        if only_contracts and contract_id not in only_contracts:
            continue

        with open(f, "r", encoding="utf-8") as fh:
            results = json.load(fh)
        if not results:
            continue

        # Pass 1
        nodes, edges, dropped, unmapped = normalize_contract(
            contract_id=contract_id, tenant_id=tenant_id, extraction_results=results,
        )
        for k, v in dropped.items():
            graph.dropped_edges[k] = graph.dropped_edges.get(k, 0) + v
        for k, v in unmapped.items():
            graph.unmapped_labels[k] = graph.unmapped_labels.get(k, 0) + v

        # Pass 2 (per contract)
        nodes, edges = resolve_contract(nodes, edges)

        for n in nodes:
            graph.nodes[n.kgId] = n
        for e in edges:
            graph.edges[e.edgeId] = e

    # Pass 3 (global)
    canonicals, resolved_as = canonicalize(list(graph.nodes.values()))
    graph.canonicals = canonicals
    graph.resolved_as = resolved_as

    return graph
