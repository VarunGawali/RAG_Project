"""
Audit the deterministic resolution pipeline on saved extractions — WRITES NOTHING
to Gremlin. Shows what the rebuilt graph would look like so we can validate the
design before clearing/writing the live KG.

    python -m app.scripts.audit_kg_resolution
    python -m app.scripts.audit_kg_resolution --dir data/kg/extractions --dump data/kg/resolved

The optional --dump writes the resolved graph as JSON artifacts (still no Gremlin).
"""

import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from app.kg.resolution.pipeline import run_pipeline


def sect(t):
    print("\n" + "=" * 70 + f"\n  {t}\n" + "=" * 70)


def main():
    ap = argparse.ArgumentParser("audit-kg-resolution")
    ap.add_argument("--dir", default="data/kg/extractions")
    ap.add_argument("--tenant-id", default="default")
    ap.add_argument("--dump", default=None, help="Optional dir to write resolved JSON")
    args = ap.parse_args()

    g = run_pipeline(args.dir, tenant_id=args.tenant_id)

    nodes = list(g.nodes.values())
    contracts = sorted({n.contractId for n in nodes})

    sect("1. Totals")
    print(f"  Contracts:            {len(contracts)}")
    print(f"  Mention nodes:        {len(nodes)}")
    print(f"  Edges (entity↔entity):{len(g.edges)}")
    print(f"  CanonicalEntity:      {len(g.canonicals)}")
    print(f"  RESOLVED_AS edges:    {len(g.resolved_as)}")

    sect("2. Node labels (slim ontology)")
    for label, n in Counter(x.label for x in nodes).most_common():
        print(f"  {label:<22} {n}")

    sect("2b. Subtypes (top 20)")
    for (lab, sub), n in Counter(
        (x.label, x.subtype) for x in nodes if x.subtype
    ).most_common(20):
        print(f"  {lab}/{sub:<22} {n}")

    sect("3. Edge labels")
    for label, n in Counter(e.label for e in g.edges.values()).most_common():
        print(f"  {label:<28} {n}")

    sect("4. Dropped edges (Pass 1)")
    for k, v in sorted(g.dropped_edges.items(), key=lambda x: -x[1]):
        print(f"  {k:<40} {v}")
    if g.unmapped_labels:
        sect("4b. Unmapped entity types (kept as Concept — review)")
        for k, v in sorted(g.unmapped_labels.items(), key=lambda x: -x[1]):
            print(f"  {k:<28} {v}")

    sect("5. Party de-fragmentation (entityClass)")
    parties = [n for n in nodes if n.label in ("Party", "GovernmentalAuthority")]
    cls = Counter(p.entityClass for p in parties)
    print(f"  Party/GovAuth nodes: {len(parties)}  → {dict(cls)}")
    # show any still-fragmented (contract,name) — should be ~none now
    by_key = Counter((p.contractId, p.normalizedName) for p in parties)
    frag = [(k, c) for k, c in by_key.items() if c > 1]
    print(f"  (contract, normalizedName) pairs with >1 node: {len(frag)}")
    for (cid, name), c in sorted(frag, key=lambda x: -x[1])[:10]:
        print(f"    {c}  [{cid}] {name!r}")

    sect("6. CanonicalEntities (cross-contract identity)")
    multi = [c for c in g.canonicals.values() if len(c.contractIds) > 1]
    print(f"  Canonicals spanning >1 contract: {len(multi)}")
    for c in sorted(g.canonicals.values(), key=lambda x: -len(x.contractIds))[:25]:
        span = f"{len(c.contractIds)}c"
        print(f"  [{c.entityClass:<9}] {c.canonicalName:<34} {span:<4} "
              f"aliases={c.aliases[:4]}")

    sect("7. Con Edison vs SCE guard check")
    for cid in ("canonical:org:con_edison", "canonical:org:southern_california_edison"):
        c = g.canonicals.get(cid)
        if c:
            print(f"  {c.canonicalName}: contracts={c.contractIds} aliases={c.aliases}")
        else:
            print(f"  {cid}: (not present)")

    if args.dump:
        out = Path(args.dump)
        out.mkdir(parents=True, exist_ok=True)
        json.dump([asdict(n) for n in nodes], open(out / "nodes.json", "w"), indent=1, default=str)
        json.dump([asdict(e) for e in g.edges.values()], open(out / "edges.json", "w"), indent=1, default=str)
        json.dump([asdict(c) for c in g.canonicals.values()], open(out / "canonicals.json", "w"), indent=1, default=str)
        json.dump([asdict(e) for e in g.resolved_as], open(out / "resolved_as.json", "w"), indent=1, default=str)
        print(f"\n  Dumped resolved graph JSON → {out}/  (no Gremlin writes)")

    print("\nAudit complete. Nothing was written to Gremlin.\n")


if __name__ == "__main__":
    main()
