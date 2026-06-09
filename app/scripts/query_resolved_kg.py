"""
Offline query tester for the RESOLVED graph (data/kg/resolved/*.json).

Runs the same traversals the future Gremlin retriever will — but on the local
JSON, so we can validate relationship/cross-contract context before writing
anything to Cosmos.

    python -m app.scripts.query_resolved_kg                       # demo queries
    python -m app.scripts.query_resolved_kg --entity "Con Edison" # ad-hoc

Edge directions (from extraction):
    Obligation -OWED_BY-> Party    (obligation owed BY party)
    Obligation -OWED_TO-> Party    (obligation owed TO party)
    Obligation -HAS_DEADLINE-> TemporalConstraint
    Party      -RESOLVED_AS-> CanonicalEntity
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from app.kg.resolution.model import normalize_name


class ResolvedKG:
    def __init__(self, d="data/kg/resolved"):
        p = Path(d)
        self.nodes = {n["kgId"]: n for n in json.load(open(p / "nodes.json"))}
        self.edges = json.load(open(p / "edges.json"))
        self.canon = {c["id"]: c for c in json.load(open(p / "canonicals.json"))}
        self.resolved_as = json.load(open(p / "resolved_as.json"))

        # adjacency
        self.out = defaultdict(list)   # src → [(label, dst, edge)]
        self.inc = defaultdict(list)   # dst → [(label, src, edge)]
        for e in self.edges:
            self.out[e["sourceId"]].append((e["label"], e["targetId"], e))
            self.inc[e["targetId"]].append((e["label"], e["sourceId"], e))

        # mention → canonical
        self.mention_to_canon = {r["sourceId"]: r["targetId"] for r in self.resolved_as}
        self.canon_to_mentions = defaultdict(list)
        for m, c in self.mention_to_canon.items():
            self.canon_to_mentions[c].append(m)

        # name lookups
        self.by_norm = defaultdict(list)
        for n in self.nodes.values():
            self.by_norm[n["normalizedName"]].append(n["kgId"])
        self.canon_alias = {}
        for c in self.canon.values():
            for a in c["aliases"]:
                self.canon_alias[normalize_name(a)] = c["id"]
            self.canon_alias[normalize_name(c["canonicalName"])] = c["id"]

    # ── resolution ──────────────────────────────────────────────────────
    def resolve_party_ids(self, name):
        """Return all party mention ids for a name (via canonical if known)."""
        nn = normalize_name(name)
        cid = self.canon_alias.get(nn)
        if cid:
            ids = list(self.canon_to_mentions.get(cid, []))
            if ids:
                return ids, cid
        # fall back to direct name match on Party nodes
        ids = [i for i in self.by_norm.get(nn, [])
               if self.nodes[i]["label"] in ("Party", "GovernmentalAuthority")]
        return ids, cid

    # ── queries ─────────────────────────────────────────────────────────
    def obligations_of(self, party_name):
        """Obligations owed BY a party (across all its mentions/contracts)."""
        ids, cid = self.resolve_party_ids(party_name)
        idset = set(ids)
        out = []
        for e in self.edges:
            if e["label"] == "OWED_BY" and e["targetId"] in idset:
                o = self.nodes.get(e["sourceId"])
                if o:
                    out.append(o)
        return out, cid, ids

    def cross_contract(self, entity_name):
        nn = normalize_name(entity_name)
        cid = self.canon_alias.get(nn)
        if not cid:
            return None
        return self.canon[cid]

    def context(self, node_id, limit=12):
        """Relationship neighborhood of a node (for eyeballing context)."""
        lines = []
        for label, dst, _ in self.out.get(node_id, [])[:limit]:
            t = self.nodes.get(dst) or self.canon.get(dst) or {}
            nm = t.get("name") or t.get("canonicalName") or dst
            lines.append(f"   -{label}-> [{t.get('label','?')}] {nm}")
        for label, src, _ in self.inc.get(node_id, [])[:limit]:
            s = self.nodes.get(src) or {}
            lines.append(f"   <-{label}- [{s.get('label','?')}] {s.get('name', src)}")
        return lines


def _fmt_obl(o):
    pg = f" (pp.{o['pageStart']}-{o['pageEnd']})" if o.get("pageStart") else ""
    return f"  [{o['contractId']}] {o['name']}{pg}"


def demo(kg: ResolvedKG):
    print("\n### Q1. What are Con Edison's obligations? (single named entity)")
    obls, cid, ids = kg.obligations_of("Con Edison")
    print(f"  resolved → {cid}  ({len(ids)} mention nodes, {len(obls)} obligations)")
    for o in obls[:8]:
        print(_fmt_obl(o))

    print("\n### Q2. Power Authority obligations (defined-term party)")
    obls, cid, ids = kg.obligations_of("Power Authority")
    print(f"  resolved → {cid}  ({len(obls)} obligations)")
    for o in obls[:6]:
        print(_fmt_obl(o))

    print("\n### Q3. Cross-contract: which contracts reference NERC?")
    c = kg.cross_contract("NERC")
    if c:
        print(f"  {c['canonicalName']} appears in {len(c['contractIds'])} contract(s): {c['contractIds']}")

    print("\n### Q4. Cross-contract: NYISO")
    c = kg.cross_contract("NYISO")
    if c:
        print(f"  {c['canonicalName']} appears in {len(c['contractIds'])} contract(s): {c['contractIds']}")

    print("\n### Q5. Edison-trap check: 'Edison' resolves to which entity?")
    c = kg.cross_contract("Edison")
    if c:
        print(f"  'Edison' → {c['canonicalName']} {c['contractIds']}  (NOT Con Edison ✔)")

    print("\n### Q6. Relationship context for one Con Edison obligation")
    obls, _, _ = kg.obligations_of("Con Edison")
    if obls:
        o = obls[0]
        print(f"  {o['name']}")
        for line in kg.context(o["kgId"]):
            print(line)


def main():
    ap = argparse.ArgumentParser("query-resolved-kg")
    ap.add_argument("--dir", default="data/kg/resolved")
    ap.add_argument("--entity", default=None, help="Show obligations + cross-contract for an entity")
    args = ap.parse_args()

    kg = ResolvedKG(args.dir)

    if args.entity:
        obls, cid, ids = kg.obligations_of(args.entity)
        print(f"\nEntity '{args.entity}' → canonical {cid}")
        print(f"  mention nodes: {len(ids)} | obligations owed by: {len(obls)}")
        for o in obls[:15]:
            print(_fmt_obl(o))
        c = kg.cross_contract(args.entity)
        if c:
            print(f"  cross-contract: {c['contractIds']}")
        return

    demo(kg)
    print()


if __name__ == "__main__":
    main()
