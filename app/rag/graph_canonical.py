"""
Canonical-anchored graph retrieval (Phase 1) + Azure Search vector bridge (Phase 2).

This is the "smart" retriever that exploits the two-tier canonical graph:

  Phase 1 — entity-linked:
     question → link to CanonicalEntity → RESOLVED_AS → mention parties →
     OWED_BY/OWED_TO → obligations/rights (bounded), with cross-contract reach.

  Phase 2 — no entity linked (e.g. "force majeure clauses"):
     reuse the existing Azure AI Search vector index → relevant clause ids →
     anchor graph nodes via sourceClauseId → serialize their neighborhood.

Bounded by design (limits everywhere) so a portfolio question can't dump the
whole graph into the prompt (the old 429 cause).
"""

import logging
from typing import Dict, List, Optional

from app.kg.gremlin_writer import GremlinWriter
from app.kg.resolution.model import normalize_name

logger = logging.getLogger(__name__)

# Bounds (keep context small + RU cheap)
MAX_OBLIGATIONS_PER_ENTITY = 40
MAX_ENTITIES = 5
MAX_VECTOR_CLAUSES = 8
MAX_SUBGRAPH_FACTS = 40


def _fv(m: Dict, k: str, default=None):
    v = m.get(k, default)
    return v[0] if isinstance(v, list) and v else (default if isinstance(v, list) else v)


class CanonicalGraphRetriever:
    def __init__(self):
        self.w = GremlinWriter()
        self._canon_cache: Optional[List[Dict]] = None

    def close(self):
        self.w.close()

    # ── entity linking ──────────────────────────────────────────────────
    def _canonicals(self) -> List[Dict]:
        if self._canon_cache is None:
            rows = self.w.submit(
                "g.V().hasLabel('CanonicalEntity')"
                ".valueMap('kgId','canonicalName','entityClass','aliases')"
            )
            out = []
            for r in rows:
                cid = _fv(r, "kgId")
                name = _fv(r, "canonicalName") or ""
                aliases_raw = _fv(r, "aliases") or "[]"
                # aliases stored as JSON string by clean_value
                import json
                try:
                    aliases = json.loads(aliases_raw) if isinstance(aliases_raw, str) else list(aliases_raw)
                except Exception:
                    aliases = []
                surface = {normalize_name(name)} | {normalize_name(a) for a in aliases}
                out.append({"id": cid, "name": name, "surfaces": {s for s in surface if s}})
            self._canon_cache = out
        return self._canon_cache

    def link_entities(self, question: str) -> List[Dict]:
        """
        Link canonical entities mentioned in the question, with span-aware
        longest-match so a longer surface ("con edison") claims its span and
        blocks an overlapping shorter alias of a DIFFERENT entity ("edison" → SCE).
        This is what keeps the Edison trap closed at the linking layer.
        """
        q = normalize_name(question)

        # collect (start, end, length, canonical) for every word-bounded surface hit
        candidates = []
        for c in self._canonicals():
            for s in c["surfaces"]:
                if len(s) < 3:
                    continue
                start = 0
                while True:
                    i = q.find(s, start)
                    if i < 0:
                        break
                    j = i + len(s)
                    before_ok = i == 0 or not q[i - 1].isalnum()
                    after_ok = j == len(q) or not q[j].isalnum()
                    if before_ok and after_ok:
                        candidates.append((i, j, len(s), c))
                    start = i + 1

        # longest first; greedily claim non-overlapping spans
        candidates.sort(key=lambda x: -x[2])
        taken, chosen, seen = [], [], set()
        for st, en, _ln, c in candidates:
            if any(not (en <= ts or st >= te) for ts, te in taken):
                continue
            taken.append((st, en))
            if c["id"] not in seen:
                seen.add(c["id"])
                chosen.append(c)
        return chosen[:MAX_ENTITIES]

    # ── traversals ──────────────────────────────────────────────────────
    def contracts_for(self, canon_id: str) -> List[str]:
        rows = self.w.submit(
            "g.V(cid).in('RESOLVED_AS').values('contractId').dedup()",
            {"cid": canon_id},
        )
        return sorted({r for r in rows if r})

    def obligations_for(self, canon_id: str, edge: str, scope: Optional[List[str]],
                        limit: int = MAX_OBLIGATIONS_PER_ENTITY) -> List[Dict]:
        """edge = 'OWED_BY' (owed by entity) or 'OWED_TO' (owed to entity)."""
        rows = self.w.submit(
            f"g.V(cid).in('RESOLVED_AS').in('{edge}').hasLabel('Obligation').dedup()"
            f".limit({limit})"
            ".valueMap('kgId','name','contractId','confidence','evidenceQuote','clauseTitle','pageStart','pageEnd')",
            {"cid": canon_id},
        )
        facts = [self._norm_fact(r) for r in rows]
        if scope:
            facts = [f for f in facts if f["contractId"] in set(scope)]
        return facts

    def subgraph_from_clauses(self, clause_ids: List[str],
                              scope: Optional[List[str]]) -> List[Dict]:
        """Phase 2: anchor graph nodes on clause ids from vector search."""
        if not clause_ids:
            return []
        # Cosmos `within` with a bound list
        rows = self.w.submit(
            "g.V().has('sourceClauseId', within(cids))"
            ".hasLabel('Obligation','Right','Restriction','Event').dedup()"
            f".limit({MAX_SUBGRAPH_FACTS})"
            ".valueMap('kgId','name','legalType','contractId','confidence','evidenceQuote','clauseTitle','pageStart','pageEnd')",
            {"cids": clause_ids},
        )
        facts = [self._norm_fact(r) for r in rows]
        if scope:
            facts = [f for f in facts if f["contractId"] in set(scope)]
        return facts

    @staticmethod
    def _norm_fact(r: Dict) -> Dict:
        return {
            "kgId": _fv(r, "kgId"),
            "name": _fv(r, "name"),
            "legalType": _fv(r, "legalType"),
            "contractId": _fv(r, "contractId"),
            "confidence": _fv(r, "confidence", 0.0),
            "evidenceQuote": _fv(r, "evidenceQuote"),
            "clauseTitle": _fv(r, "clauseTitle"),
            "pageStart": _fv(r, "pageStart"),
            "pageEnd": _fv(r, "pageEnd"),
        }


# ── serialization ───────────────────────────────────────────────────────────────

def _fmt(facts: List[Dict]) -> List[str]:
    lines = []
    for i, f in enumerate(facts, 1):
        line = f"  {i}. {f.get('name') or '(unnamed)'}"
        if f.get("contractId"):
            line += f"   [{f['contractId']}]"
        lines.append(line)
        if f.get("clauseTitle"):
            pg = f" (pp.{f['pageStart']}-{f['pageEnd']})" if f.get("pageStart") else ""
            lines.append(f"     Source: {f['clauseTitle']}{pg}")
        if f.get("evidenceQuote"):
            lines.append(f"     Evidence: \"{f['evidenceQuote']}\"")
    return lines


def canonical_graph_retrieve(
    question: str,
    contract_id: Optional[str] = None,
    contract_ids: Optional[List[str]] = None,
    search_anchor_fn=None,
):
    """
    Smart graph retrieval. Returns (context_str, facts) where `facts` is the list
    of structured fact dicts (with clauseTitle/pageStart/contractId/evidenceQuote)
    so the caller can build real citations. Returns ("", []) if nothing found.

    search_anchor_fn(question, scope) -> List[clause_id]  (Phase-2 bridge; optional)
    """
    scope = list(contract_ids) if contract_ids else ([contract_id] if contract_id else None)
    qlow = question.lower()
    # Direction: "obligations owed TO X" → OWED_TO; otherwise the common case
    # ("X's obligations" / "what does X owe") → OWED_BY only. This avoids
    # conflating duties-of vs duties-toward and roughly halves the result set.
    want_to = "owed to" in qlow or "owe to" in qlow or "owing to" in qlow
    want_by = not want_to

    r = CanonicalGraphRetriever()
    all_facts: List[Dict] = []
    try:
        linked = r.link_entities(question)
        blocks: List[str] = []

        if linked:
            for c in linked:
                contracts = r.contracts_for(c["id"])
                owed_by = r.obligations_for(c["id"], "OWED_BY", scope) if want_by else []
                owed_to = r.obligations_for(c["id"], "OWED_TO", scope) if want_to else []
                header = [
                    "=" * 70,
                    f"ENTITY: {c['name']}   (appears in {len(contracts)} contract(s): {contracts})",
                    "=" * 70,
                ]
                if owed_by:
                    header.append(f"Obligations owed BY {c['name']} ({len(owed_by)}):")
                    header += _fmt(owed_by)
                    all_facts += owed_by
                if owed_to:
                    header.append(f"Obligations owed TO {c['name']} ({len(owed_to)}):")
                    header += _fmt(owed_to)
                    all_facts += owed_to
                if owed_by or owed_to:
                    blocks.append("\n".join(header))

        # Phase-2 vector bridge when no entity facts found
        if not blocks and search_anchor_fn is not None:
            clause_ids = search_anchor_fn(question, scope) or []
            facts = r.subgraph_from_clauses(clause_ids[:MAX_VECTOR_CLAUSES], scope)
            if facts:
                blocks.append(
                    "=" * 70 + "\nGRAPH FACTS (anchored on relevant clauses)\n" + "=" * 70
                    + "\n" + "\n".join(_fmt(facts))
                )
                all_facts += facts

        return "\n\n".join(blocks), all_facts
    except Exception as exc:
        logger.warning("canonical_graph_retrieve failed (%s) — caller should fall back.", exc)
        return "", []
    finally:
        r.close()