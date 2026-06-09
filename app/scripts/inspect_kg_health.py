"""
KG health & cross-contract readiness diagnostic.

Run on a machine with the Gremlin env vars set:

    python -m app.scripts.inspect_kg_health

Unlike check_semantic_kg / check_structural_kg (which only print aggregate
counts), this answers the questions that decide the entity-resolution /
cross-contract redesign:

  1. Which contracts are actually in the graph, and how big is each?
  2. Entity-label and edge-label distribution.
  3. PARTY FRAGMENTATION — is the same party split into many vertices
     (per-clause) within a single contract? (the #1 thing to confirm)
  4. CROSS-CONTRACT NAME OVERLAP — which party names appear in >1 contract,
     and would naive string-matching unify them?
  5. CONNECTIVITY — what fraction of Obligations actually have OWED_BY /
     HAS_DEADLINE edges (i.e. is this a connected graph or a bag of stars)?
  6. A couple of concrete sample traversals so you can eyeball real data.

Nothing is written. Read-only.
"""

from collections import defaultdict
from typing import Any, Dict, List

from app.kg.gremlin_writer import GremlinWriter
from app.rag.graph_retriever import PARTY_LABELS, first_value


def gremlin_is_configured() -> bool:
    from app import config
    return all([
        getattr(config, "GREMLIN_ENDPOINT", None),
        getattr(config, "GREMLIN_USERNAME", None),
        getattr(config, "GREMLIN_PASSWORD", None),
    ])


def _v(prop_map: Dict[str, Any], key: str):
    return first_value(prop_map, key)


def section(title: str):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def main():
    if not gremlin_is_configured():
        print("Gremlin not configured — set GREMLIN_ENDPOINT/USERNAME/PASSWORD.")
        return

    w = GremlinWriter()
    try:
        # ── 1. Contracts in the graph ──────────────────────────────────
        section("1. Contracts present in the semantic graph")
        contract_ids = sorted(set(
            w.submit("g.V().has('nodeType','legal_entity').values('contractId').dedup()")
        ))
        print(f"  {len(contract_ids)} contract(s): {contract_ids}")

        total_v = w.submit("g.V().has('nodeType','legal_entity').count()")[0]
        total_e = w.submit("g.E().count()")[0]
        print(f"  Total legal-entity vertices: {total_v}")
        print(f"  Total edges (all):           {total_e}")

        print("\n  Per-contract vertex counts:")
        for cid in contract_ids:
            c = w.submit(
                "g.V().has('nodeType','legal_entity').has('contractId', cid).count()",
                {"cid": cid},
            )[0]
            print(f"    {cid:<45} {c}")

        # ── 2. Label distributions ─────────────────────────────────────
        section("2. Entity-label distribution (legal_entity vertices)")
        label_counts = w.submit(
            "g.V().has('nodeType','legal_entity').groupCount().by(label)"
        )
        for label, count in sorted(label_counts[0].items(), key=lambda x: -x[1]):
            print(f"    {label:<30} {count}")

        section("2b. Edge-label distribution")
        edge_counts = w.submit("g.E().groupCount().by(label)")
        for label, count in sorted(edge_counts[0].items(), key=lambda x: -x[1]):
            print(f"    {label:<35} {count}")

        # ── 3. Party fragmentation within a contract ───────────────────
        section("3. PARTY FRAGMENTATION  (same name → how many vertices?)")
        party_label_args = ", ".join(f"'{l}'" for l in PARTY_LABELS)
        party_rows = w.submit(
            f"g.V().hasLabel({party_label_args}).valueMap('contractId','name','kgId')"
        )
        # group by (contractId, name) -> list of distinct kgIds
        grp: Dict[tuple, set] = defaultdict(set)
        for r in party_rows:
            key = (_v(r, "contractId"), (_v(r, "name") or "").strip())
            grp[key].add(_v(r, "kgId"))

        frag = sorted(
            ((cid, name, len(ids)) for (cid, name), ids in grp.items()),
            key=lambda x: -x[2],
        )
        print("  (contractId, party name) → distinct vertices  [>1 = fragmented]")
        for cid, name, n in frag[:25]:
            flag = "  <-- FRAGMENTED" if n > 1 else ""
            print(f"    {n:>3}  [{cid}] {name!r}{flag}")
        fragmented = sum(1 for *_, n in frag if n > 1)
        print(f"\n  {fragmented}/{len(frag)} (contract,name) pairs are fragmented "
              f"into multiple vertices.")

        # ── 4. Cross-contract name overlap ─────────────────────────────
        section("4. CROSS-CONTRACT party-name overlap (naive string match)")
        name_to_contracts: Dict[str, set] = defaultdict(set)
        for r in party_rows:
            name = (_v(r, "name") or "").strip()
            cid = _v(r, "contractId")
            if name and cid:
                name_to_contracts[name].add(cid)
        shared = {n: cs for n, cs in name_to_contracts.items() if len(cs) > 1}
        if shared:
            print("  Names appearing in >1 contract (would unify via exact match):")
            for name, cs in sorted(shared.items()):
                print(f"    {name!r}: {sorted(cs)}")
        else:
            print("  No party name appears in >1 contract via EXACT match.")
        print("\n  NOTE: variants like 'Con Edison' vs 'Consolidated Edison Company"
              " of New York, Inc.' will NOT show here — that gap is the case for"
              " entity resolution.")
        print("  Distinct party names across the whole graph:")
        for name in sorted(name_to_contracts):
            print(f"    {name!r}  in {sorted(name_to_contracts[name])}")

        # ── 5. Connectivity of obligations ─────────────────────────────
        section("5. CONNECTIVITY — are Obligations actually linked?")
        total_obl = w.submit("g.V().hasLabel('Obligation').count()")[0]
        with_owed_by = w.submit(
            "g.V().hasLabel('Obligation').where(out('OWED_BY')).count()"
        )[0]
        with_obligates = w.submit(
            "g.V().hasLabel('Obligor').where(out('OBLIGATES')).count()"
        )[0]
        with_deadline = w.submit(
            "g.V().hasLabel('Obligation').where(out('HAS_DEADLINE')).count()"
        )[0]
        isolated = w.submit(
            "g.V().hasLabel('Obligation').where(__.not(bothE())).count()"
        )[0]
        print(f"  Total Obligation vertices:            {total_obl}")
        print(f"  ...with an OWED_BY edge:              {with_owed_by}")
        print(f"  Obligor vertices with OBLIGATES edge: {with_obligates}")
        print(f"  ...with a HAS_DEADLINE edge:          {with_deadline}")
        print(f"  Obligation vertices with NO edges:    {isolated}  "
              f"(isolated = unreachable by traversal)")

        # ── 6. Sample traversal ────────────────────────────────────────
        section("6. Sample: first 5 Obligations + their party (if any)")
        sample = w.submit(
            "g.V().hasLabel('Obligation').limit(5)"
            ".project('name','contractId','party')"
            ".by('name').by('contractId')"
            ".by(coalesce(out('OWED_BY').values('name'), constant('<none>')).fold())"
        )
        for s in sample:
            print(f"    [{s.get('contractId')}] {s.get('name')!r}"
                  f"  owed_by={s.get('party')}")

        print("\nDone. Read-only — nothing was modified.\n")

    finally:
        w.close()


if __name__ == "__main__":
    main()
