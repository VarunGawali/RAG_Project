"""
Rebuild the semantic KG in Cosmos Gremlin from the resolved graph.

SAFE BY DEFAULT: with no flags it runs the resolution pipeline, validates, and
prints the write plan — but writes NOTHING. The destructive clear+write requires
explicit flags and a typed confirmation.

Typical sequence
----------------
  # 1. Plan only (no Gremlin needed):
  python -m app.scripts.rebuild_semantic_kg

  # 2. Small dry-run write of ONE contract, no clearing (prove the writer):
  python -m app.scripts.rebuild_semantic_kg --contract SoCal_EPC --write --no-clear

  # 3. Full rebuild (clears the semantic KG, then writes all):
  python -m app.scripts.rebuild_semantic_kg --write --clear --yes

Flags
-----
  --write        actually write to Gremlin (otherwise plan-only)
  --clear        drop the existing semantic vertices first (full rebuild)
  --no-clear     write without clearing (incremental / single-contract test)
  --contract ID  scope the pipeline to one contract
  --yes          skip the typed confirmation
  --delay SEC    RU pacing between writes (default 0.4)
"""

import argparse
import sys
import time

from app.kg.resolution.pipeline import run_pipeline
from app.kg.resolution.graph_writer import (
    node_props, canonical_props, edge_props, validate_edges,
)

# Labels to drop on --clear: old ontology + new slim core + canonical layer.
NEW_CORE_LABELS = [
    "Party", "GovernmentalAuthority", "Obligation", "Right", "Restriction",
    "TemporalConstraint", "Event", "Condition", "FinancialTerm", "Instrument",
    "Concept", "CanonicalEntity",
]


def _tenant():
    try:
        from app import config
        return getattr(config, "TENANT_ID", "default") or "default"
    except Exception:
        return "default"


def _gremlin_configured() -> bool:
    """Self-contained config check (avoids importing helpers that may not exist
    in every machine's gremlin_writer.py version)."""
    try:
        from app import config
        return all([
            getattr(config, "GREMLIN_ENDPOINT", None),
            getattr(config, "GREMLIN_USERNAME", None),
            getattr(config, "GREMLIN_PASSWORD", None),
        ])
    except Exception:
        return False


def _drop_batched(writer, gremlin_match: str, label: str, batch: int, delay: float):
    """
    Drop vertices/edges in small batches to stay within the RU budget.
    `gremlin_match` is a traversal up to (but excluding) the limit+drop, e.g.
    "g.V().hasLabel('Obligation')".
    """
    dropped = 0
    while True:
        try:
            writer.submit(f"{gremlin_match}.limit({batch}).drop()")
        except Exception as e:
            print(f"    drop {label} batch failed (will retry): {e}")
            time.sleep(max(delay, 1.0))
            continue
        dropped += batch
        # remaining?
        try:
            cnt = writer.submit(f"{gremlin_match}.limit(1).count()")
        except Exception:
            cnt = [1]
        if not cnt or cnt[0] == 0:
            break
        if delay:
            time.sleep(delay)
    print(f"    cleared {label}")


def _clear_semantic(writer, delay: float, batch: int = 50):
    """Drop semantic legal-entity + canonical vertices in RU-safe batches.

    Dropping a vertex cascades its edges, so vertex drops also remove OWED_BY etc.
    """
    from app.kg.legal_extractor import LEGAL_NODE_TYPES
    labels = sorted(set(LEGAL_NODE_TYPES) | set(NEW_CORE_LABELS))
    print(f"  Clearing {len(labels)} semantic labels (batch={batch})...")
    # legacy provenance edges first (in case structural vertices remain)
    _drop_batched(writer, "g.E().hasLabel('EXTRACTED_ENTITY')", "EXTRACTED_ENTITY", batch, delay)
    for label in labels:
        _drop_batched(writer, f"g.V().hasLabel('{label}')", label, batch, delay)
    # belt-and-suspenders: anything still tagged as a semantic node
    for nt in ("legal_entity", "canonical_entity"):
        _drop_batched(writer, f"g.V().has('nodeType','{nt}')", f"nodeType={nt}", batch, delay)
    print("  Clear complete.")


def main():
    ap = argparse.ArgumentParser("rebuild-semantic-kg")
    ap.add_argument("--extractions-dir", default="data/kg/extractions")
    ap.add_argument("--tenant-id", default=None)
    ap.add_argument("--contract", default=None, help="Scope to one contract id")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--no-clear", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--delay", type=float, default=0.1)
    ap.add_argument("--clear-batch", type=int, default=50,
                    help="Vertices dropped per request during --clear (RU-safe)")
    args = ap.parse_args()

    tenant = args.tenant_id or _tenant()
    only = [args.contract] if args.contract else None

    # ── Locate inputs (fail loudly instead of writing 0) ────────────────
    from pathlib import Path
    ex_dir = Path(args.extractions_dir)
    found = sorted(p.stem.replace("_legal_extractions", "")
                   for p in ex_dir.glob("*_legal_extractions.json"))
    if not found:
        print(f"\n  ERROR: no '*_legal_extractions.json' files in {ex_dir.resolve()}")
        print("  Pass the right path with --extractions-dir, e.g.")
        print("    --extractions-dir C:\\Users\\WW773GE\\Downloads\\demo1\\rag_system_for_contracts\\data\\kg\\extractions")
        sys.exit(1)
    if args.contract and args.contract not in found:
        print(f"\n  ERROR: --contract '{args.contract}' not found in {ex_dir.resolve()}")
        print(f"  Available contract ids ({len(found)}):")
        for c in found:
            print(f"    {c}")
        sys.exit(1)

    # ── Pipeline (no Gremlin needed) ────────────────────────────────────
    g = run_pipeline(args.extractions_dir, tenant_id=tenant, only_contracts=only)
    sem_edges, res_edges, skipped = validate_edges(g)

    print("\n" + "=" * 64)
    print("  WRITE PLAN")
    print("=" * 64)
    print(f"  tenant:            {tenant}")
    print(f"  contract scope:    {args.contract or 'ALL'}")
    print(f"  mention vertices:  {len(g.nodes)}")
    print(f"  canonical vertices:{len(g.canonicals)}")
    print(f"  semantic edges:    {len(sem_edges)}")
    print(f"  RESOLVED_AS edges: {len(res_edges)}")
    if skipped:
        print("  skipped (orphan endpoints):")
        for k, v in sorted(skipped.items(), key=lambda x: -x[1]):
            print(f"     {k:<40} {v}")
    total_writes = len(g.nodes) + len(g.canonicals) + len(sem_edges) + len(res_edges)
    print(f"  TOTAL Gremlin upserts: {total_writes}")
    est = total_writes * args.delay
    print(f"  est. pacing time: ~{est/60:.1f} min at {args.delay}s/op")

    if not args.write:
        print("\n  PLAN ONLY — nothing written. Re-run with --write to execute.\n")
        return

    if args.clear and args.no_clear:
        print("\n  ERROR: pass either --clear or --no-clear, not both.")
        sys.exit(1)

    # ── Confirmation ────────────────────────────────────────────────────
    if not args.yes:
        action = "CLEAR the semantic KG and " if args.clear else ""
        print(f"\n  About to {action}write {total_writes} elements to Gremlin.")
        if input("  Type 'yes' to proceed: ").strip().lower() != "yes":
            print("  Aborted.")
            return

    # ── Write ───────────────────────────────────────────────────────────
    from app.kg.gremlin_writer import GremlinWriter
    if not _gremlin_configured():
        print("\n  ERROR: Gremlin not configured (GREMLIN_ENDPOINT/USERNAME/PASSWORD).")
        sys.exit(1)

    writer = GremlinWriter()
    try:
        if args.clear:
            _clear_semantic(writer, args.delay, batch=args.clear_batch)

        print(f"\n  Writing {len(g.nodes)} mention vertices...")
        for i, n in enumerate(g.nodes.values(), 1):
            writer.upsert_vertex(label=n.label, vertex_id=n.kgId, pk=n.tenantId,
                                 properties=node_props(n))
            if args.delay:
                time.sleep(args.delay)
            if i % 100 == 0:
                print(f"    {i}/{len(g.nodes)}")

        print(f"  Writing {len(g.canonicals)} canonical vertices...")
        for c in g.canonicals.values():
            writer.upsert_vertex(label="CanonicalEntity", vertex_id=c.id, pk=tenant,
                                 properties=canonical_props(c))
            if args.delay:
                time.sleep(args.delay)

        print(f"  Writing {len(sem_edges)} semantic edges...")
        for i, e in enumerate(sem_edges, 1):
            writer.upsert_edge(source_id=e.sourceId, target_id=e.targetId,
                               edge_label=e.label, properties=edge_props(e))
            if args.delay:
                time.sleep(args.delay)
            if i % 200 == 0:
                print(f"    {i}/{len(sem_edges)}")

        print(f"  Writing {len(res_edges)} RESOLVED_AS edges...")
        for e in res_edges:
            writer.upsert_edge(source_id=e.sourceId, target_id=e.targetId,
                               edge_label="RESOLVED_AS", properties=edge_props(e))
            if args.delay:
                time.sleep(args.delay)

        print("\n  Rebuild complete. Verifying counts...")
        v = writer.submit("g.V().has('nodeType','legal_entity').count()")
        cv = writer.submit("g.V().hasLabel('CanonicalEntity').count()")
        ev = writer.submit("g.E().count()")
        print(f"    legal_entity vertices: {v}")
        print(f"    CanonicalEntity:       {cv}")
        print(f"    total edges:           {ev}")
    finally:
        writer.close()

    print("\nDone.\n")


if __name__ == "__main__":
    main()
