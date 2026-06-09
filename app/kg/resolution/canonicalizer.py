"""
Pass 3 — global canonicalization (cross-contract identity).

For every `named` Party / GovernmentalAuthority node across all contracts:
  - match to a CanonicalEntity (regulators → KNOWN_CANONICALS → org fallback)
  - create RESOLVED_AS edge (mention → canonical)
  - accumulate aliases / contractIds / mentionCount

Role placeholders are NEVER canonicalized. Distinct orgs are kept apart by the
explicit alias clusters (Con Edison ≠ Southern California Edison).

Pure stdlib. See docs/kg_redesign_spec.md §6 Pass 3.
"""

from typing import Dict, List, Optional, Tuple

from app.kg.resolution import ontology as ont
from app.kg.resolution.model import CanonicalEntity, Edge, Node, slug


def _match_canonical(normalized_name: str) -> Optional[Tuple[str, str, str]]:
    """Return (canonical_id, canonicalName, entityClass) or None (use fallback)."""
    return ont.NAMED_ALIAS_INDEX.get(normalized_name)


def canonicalize(nodes: List[Node]) -> Tuple[Dict[str, CanonicalEntity], List[Edge]]:
    """Build CanonicalEntity nodes + RESOLVED_AS edges; sets node.canonicalId in place."""
    canonicals: Dict[str, CanonicalEntity] = {}
    resolved_as: List[Edge] = []

    for n in nodes:
        if n.entityClass != "named":
            continue
        if n.label not in ("Party", "GovernmentalAuthority"):
            continue

        match = _match_canonical(n.normalizedName)
        if match:
            canon_id, canon_name, entity_class = match
        else:
            # Fallback: org-suffix named entity with no known cluster.
            # Key on normalized name so identical org strings merge across contracts.
            entity_class = "regulator" if n.label == "GovernmentalAuthority" else "org"
            canon_id = f"canonical:{entity_class}:{slug(n.normalizedName)}"
            canon_name = n.name

        ce = canonicals.get(canon_id)
        if ce is None:
            ce = CanonicalEntity(
                id=canon_id, canonicalName=canon_name, entityClass=entity_class,
            )
            canonicals[canon_id] = ce

        if n.name and n.name not in ce.aliases:
            ce.aliases.append(n.name)
        if n.contractId not in ce.contractIds:
            ce.contractIds.append(n.contractId)
        ce.mentionCount += 1

        n.canonicalId = canon_id
        resolved_as.append(Edge(
            edgeId=f"RESOLVED_AS:{n.kgId}:{canon_id}",
            label="RESOLVED_AS",
            sourceId=n.kgId,
            targetId=canon_id,
            tenantId=n.tenantId,
            contractId=n.contractId,
            confidence=n.confidence,
        ))

    return canonicals, resolved_as
