"""
Resolved-graph data model + name normalization helpers (pure stdlib).
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ── Name normalization ─────────────────────────────────────────────────────────

_POSSESSIVE_RE = re.compile(r"[’']s\b")
_NONWORD_RE = re.compile(r"[^a-z0-9]+")
_LEADING_THE_RE = re.compile(r"^the\s+")


def normalize_name(name: Optional[str]) -> str:
    """Fold case / possessives / punctuation / 'the ' for resolution matching."""
    if not name:
        return ""
    n = unicodedata.normalize("NFKC", name).strip().lower()
    n = _POSSESSIVE_RE.sub("", n)        # "client's" → "client"
    n = _LEADING_THE_RE.sub("", n)       # "the parties" → "parties"
    n = re.sub(r"\s+", " ", n).strip(" .,:;")
    return n


def slug(value: str, max_len: int = 80) -> str:
    value = unicodedata.normalize("NFKC", value or "unknown").lower()
    value = _NONWORD_RE.sub("_", value).strip("_")
    return value[:max_len] or "unknown"


# ── Resolved graph dataclasses ─────────────────────────────────────────────────

@dataclass
class Node:
    kgId: str
    label: str
    subtype: Optional[str]
    name: str
    normalizedName: str
    tenantId: str
    contractId: str

    # provenance / citation
    sourceClauseId: Optional[str] = None
    clauseTitle: Optional[str] = None
    sectionTitle: Optional[str] = None
    pageStart: Optional[int] = None
    pageEnd: Optional[int] = None
    sourcePath: Optional[str] = None
    evidenceQuote: Optional[str] = None

    # resolution
    entityClass: Optional[str] = None      # named | role | concept
    roleNormalized: Optional[str] = None
    canonicalId: Optional[str] = None

    # quality / reproducibility
    confidence: float = 0.0
    extractionModel: Optional[str] = None
    extractionVersion: Optional[str] = None
    extractedAt: Optional[str] = None

    # retrieval bridge (reserved)
    searchDocId: Optional[str] = None

    # bookkeeping (not written): raw mention count after merge
    mergedFrom: List[str] = field(default_factory=list)


@dataclass
class Edge:
    edgeId: str
    label: str
    sourceId: str
    targetId: str
    tenantId: str
    contractId: str
    role: Optional[str] = None
    evidenceQuote: Optional[str] = None
    sourceClauseId: Optional[str] = None
    confidence: float = 0.0


@dataclass
class CanonicalEntity:
    id: str
    canonicalName: str
    entityClass: str               # org | regulator | person | facility
    aliases: List[str] = field(default_factory=list)
    contractIds: List[str] = field(default_factory=list)
    mentionCount: int = 0
    searchDocId: Optional[str] = None
    label: str = "CanonicalEntity"


@dataclass
class ResolvedGraph:
    nodes: Dict[str, Node] = field(default_factory=dict)        # kgId → Node
    edges: Dict[str, Edge] = field(default_factory=dict)        # edgeId → Edge
    canonicals: Dict[str, CanonicalEntity] = field(default_factory=dict)
    resolved_as: List[Edge] = field(default_factory=list)       # RESOLVED_AS edges
    # diagnostics
    dropped_edges: Dict[str, int] = field(default_factory=dict)
    unmapped_labels: Dict[str, int] = field(default_factory=dict)
