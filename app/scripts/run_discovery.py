"""
Stage 1 script: Run open-ended discovery extraction across contracts.

Usage:

  # Single contract (specify normalized KG JSON):
  python -m app.scripts.run_discovery \
    --kg data/kg/normalized/Edison_NYPA_OandM_Contract_1_kg_ready.json \
    --limit 15

  # All normalized contracts in a folder:
  python -m app.scripts.run_discovery \
    --kg-dir data/kg/normalized \
    --limit 15

  # Dry run (print selected clauses, no LLM calls):
  python -m app.scripts.run_discovery \
    --kg data/kg/normalized/Edison_NYPA_OandM_Contract_1_kg_ready.json \
    --dry-run

Output per contract:
  data/kg/schema_discovery/{contract_id}_discovery.json
"""

import argparse
import json
from pathlib import Path

from app import config
from app.kg.models import NormalizedContract
from app.kg.clause_selector import select_representative_clauses
from app.kg.discovery_extractor import DiscoveryExtractor


DISCOVERY_DIR = config.KG_DIR / "schema_discovery"
DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)


def run_discovery_for_contract(
    kg_path: Path,
    limit: int,
    dry_run: bool,
) -> dict:
    with open(kg_path, "r", encoding="utf-8") as f:
        normalized = NormalizedContract(**json.load(f))

    selected = select_representative_clauses(normalized.nodes, limit=limit)
    contract_id = normalized.contractId

    print(f"\n{'='*70}")
    print(f"Contract: {contract_id}")
    print(f"Selected {len(selected)} clauses for discovery")

    for idx, clause in enumerate(selected, start=1):
        print(f"  {idx}. [{clause.clauseTypeHint or 'general'}] {clause.title}")

    if dry_run:
        print("DRY RUN — skipping LLM extraction")
        return {"contractId": contract_id, "dry_run": True, "selected": len(selected)}

    extractor = DiscoveryExtractor()
    results = []
    failures = []

    for idx, clause in enumerate(selected, start=1):
        print(f"\nExtracting {idx}/{len(selected)}: {clause.title}")
        try:
            result = extractor.extract_from_clause(clause)
            results.append(result.model_dump())

            entity_types = sorted({e.entity_type for e in result.entities})
            rel_types = sorted({r.relationship_type for r in result.relationships})

            print(f"  Entities ({len(result.entities)}): {entity_types}")
            print(f"  Relationships ({len(result.relationships)}): {rel_types}")

        except Exception as e:
            print(f"  FAILED: {e}")
            failures.append({"clauseKgId": clause.kgId, "error": str(e)})

    output_path = DISCOVERY_DIR / f"{contract_id}_discovery.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    summary = {
        "contractId": contract_id,
        "selectedClauses": len(selected),
        "successfulExtractions": len(results),
        "failures": len(failures),
        "output": str(output_path),
        "uniqueEntityTypes": sorted({
            e["entity_type"]
            for r in results
            for e in r.get("entities", [])
        }),
        "uniqueRelationshipTypes": sorted({
            r2["relationship_type"]
            for r in results
            for r2 in r.get("relationships", [])
        }),
    }

    print(f"\nSaved: {output_path}")
    print(f"Unique entity types discovered: {len(summary['uniqueEntityTypes'])}")
    print(f"Unique relationship types discovered: {len(summary['uniqueRelationshipTypes'])}")

    return summary


def main():
    parser = argparse.ArgumentParser("run-discovery")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--kg", help="Path to a single normalized KG JSON")
    group.add_argument("--kg-dir", help="Directory of normalized KG JSONs (runs all)")

    parser.add_argument(
        "--limit",
        type=int,
        default=15,
        help="Number of clauses to sample per contract (default: 15)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print selected clauses without running LLM extraction",
    )

    args = parser.parse_args()

    summaries = []

    if args.kg:
        kg_path = Path(args.kg)
        if not kg_path.exists():
            raise FileNotFoundError(f"KG file not found: {kg_path}")

        summary = run_discovery_for_contract(kg_path, args.limit, args.dry_run)
        summaries.append(summary)

    else:
        kg_dir = Path(args.kg_dir)
        if not kg_dir.exists():
            raise FileNotFoundError(f"KG directory not found: {kg_dir}")

        kg_files = sorted(kg_dir.glob("*_kg_ready.json"))

        if not kg_files:
            raise FileNotFoundError(f"No *_kg_ready.json files found in {kg_dir}")

        print(f"Found {len(kg_files)} contracts in {kg_dir}")

        for kg_path in kg_files:
            try:
                summary = run_discovery_for_contract(kg_path, args.limit, args.dry_run)
                summaries.append(summary)
            except Exception as e:
                print(f"ERROR processing {kg_path.name}: {e}")
                summaries.append({"file": str(kg_path), "error": str(e)})

    # Print overall summary
    print(f"\n{'='*70}")
    print("DISCOVERY COMPLETE")
    print(f"{'='*70}")
    print(json.dumps(summaries, indent=2))

    if not args.dry_run:
        # Aggregate all unique entity/rel types across all contracts
        all_entity_types = sorted({
            t
            for s in summaries
            for t in s.get("uniqueEntityTypes", [])
        })
        all_rel_types = sorted({
            t
            for s in summaries
            for t in s.get("uniqueRelationshipTypes", [])
        })

        print(f"\nTotal unique entity types across all contracts: {len(all_entity_types)}")
        print(f"Total unique relationship types across all contracts: {len(all_rel_types)}")
        print(f"\nDiscovery files saved to: {DISCOVERY_DIR}")
        print(f"\nNext step: python -m app.scripts.run_schema_induction")


if __name__ == "__main__":
    main()