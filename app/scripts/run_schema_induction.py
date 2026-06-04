"""
Stage 2 script: Run schema induction from discovery extractions.

Reads all *_discovery.json files in data/kg/schema_discovery/,
clusters raw entity/relationship type names by embedding similarity,
canonicalizes via LLM, and outputs a proposed Contract360 Legal Ontology v1.

Usage:

  python -m app.scripts.run_schema_induction

  # Custom similarity threshold (default 0.72, lower = bigger clusters):
  python -m app.scripts.run_schema_induction --threshold 0.65

  # Custom input/output paths:
  python -m app.scripts.run_schema_induction \
    --discovery-dir data/kg/schema_discovery \
    --output data/kg/schema_discovery/ontology_proposal.json

After running, review:
  data/kg/schema_discovery/ontology_proposal.json  ← main output
  data/kg/schema_discovery/clusters.json           ← inspect merges
  data/kg/schema_discovery/raw_type_occurrences.json ← all raw types

Then copy the constrained_extraction_schema section into legal_extractor.py
as your LEGAL_NODE_TYPES and LEGAL_RELATIONSHIP_TYPES for Stage 3.
"""

import argparse
import json
from pathlib import Path

from app import config
from app.kg.schema_inducer import run_schema_induction, SCHEMA_DISCOVERY_DIR


def main():
    parser = argparse.ArgumentParser("run-schema-induction")
    parser.add_argument(
        "--discovery-dir",
        default=str(SCHEMA_DISCOVERY_DIR),
        help="Directory containing *_discovery.json files",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for ontology proposal JSON",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.72,
        help=(
            "Cosine similarity threshold for clustering (default: 0.72). "
            "Lower = more aggressive merging. "
            "0.82+ = conservative (keeps more distinct types). "
            "0.70- = aggressive (merges more, fewer canonical types)."
        ),
    )

    args = parser.parse_args()

    discovery_dir = Path(args.discovery_dir)
    output_path = Path(args.output) if args.output else None

    print("Contract360 Schema Induction — Stage 2")
    print(f"Discovery dir: {discovery_dir}")
    print(f"Similarity threshold: {args.threshold}")
    print()

    ontology = run_schema_induction(
        discovery_dir=discovery_dir,
        output_path=output_path,
        similarity_threshold=args.threshold,
    )

    # Print summary
    meta = ontology.get("metadata", {})
    schema = ontology.get("constrained_extraction_schema", {})

    print("\n" + "="*70)
    print("SCHEMA INDUCTION COMPLETE")
    print("="*70)
    print(f"Contracts analyzed:        {meta.get('total_contracts_analyzed')}")
    print(f"Raw entity types found:    {meta.get('total_raw_entity_types')}")
    print(f"Raw rel types found:       {meta.get('total_raw_rel_types')}")
    print(f"Canonical entity types:    {meta.get('canonical_entity_types')}")
    print(f"Canonical rel types:       {meta.get('canonical_rel_types')}")
    print()

    # Show layer breakdown
    for layer_name, items in ontology.get("entity_types", {}).items():
        print(f"Entity {layer_name}: {len(items)} types")
        for item in items:
            print(f"  [{item['frequency_pct']}%] {item['canonical']}")

    print()
    for layer_name, items in ontology.get("relationship_types", {}).items():
        print(f"Relationship {layer_name}: {len(items)} types")
        for item in items:
            print(f"  [{item['frequency_pct']}%] {item['canonical']}")

    print()
    print("Constrained extraction schema (copy to legal_extractor.py):")
    print()
    print("LEGAL_NODE_TYPES =", json.dumps(schema.get("LEGAL_NODE_TYPES", []), indent=4))
    print()
    print("LEGAL_RELATIONSHIP_TYPES =", json.dumps(schema.get("LEGAL_RELATIONSHIP_TYPES", []), indent=4))

    output_file = output_path or SCHEMA_DISCOVERY_DIR / "ontology_proposal.json"
    print(f"\nFull proposal saved to: {output_file}")
    print("\nNext steps:")
    print("  1. Review ontology_proposal.json — check cluster merges")
    print("  2. Review clusters.json — verify no bad merges")
    print("  3. Update LEGAL_NODE_TYPES / LEGAL_RELATIONSHIP_TYPES in app/kg/legal_extractor.py")
    print("  4. Run Stage 3: python -m app.scripts.run_legal_extraction --kg <path> --limit <n>")


if __name__ == "__main__":
    main()