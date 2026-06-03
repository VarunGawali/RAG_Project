import argparse
import json
from pathlib import Path

from app import config
from app.kg.models import NormalizedContract
from app.kg.clause_selector import select_representative_clauses
from app.kg.legal_extractor import LegalLLMExtractor
from app.kg.gremlin_writer import GremlinWriter


def main():
    parser = argparse.ArgumentParser("run-legal-extraction")
    parser.add_argument(
        "--kg",
        required=True,
        help="Path to normalized KG-ready contract JSON",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=config.KG_EXTRACTION_LIMIT,
        help="Number of clauses to extract",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run extraction but do not write semantic graph to Gremlin",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON for extraction results",
    )

    args = parser.parse_args()

    kg_path = Path(args.kg)

    if not kg_path.exists():
        raise FileNotFoundError(f"KG file not found: {kg_path}")

    with open(kg_path, "r", encoding="utf-8") as f:
        normalized = NormalizedContract(**json.load(f))

    selected = select_representative_clauses(
        normalized.nodes,
        limit=args.limit,
    )

    print(f"Selected {len(selected)} clauses for extraction:")

    for idx, clause in enumerate(selected, start=1):
        print(f"{idx}. {clause.kgId} | {clause.clauseTypeHint} | {clause.title}")

    extractor = LegalLLMExtractor()
    writer = None if args.dry_run else GremlinWriter()

    results = []
    failures = []

    try:
        for idx, clause in enumerate(selected, start=1):
            print(f"\nExtracting {idx}/{len(selected)}")
            print(f"Clause: {clause.kgId}")

            try:
                result = extractor.extract_from_clause(clause)
                results.append(result)

                print(f"  Entities: {len(result.entities)}")
                print(f"  Relationships: {len(result.relationships)}")

                if writer:
                    writer.write_legal_extraction(
                        extraction=result,
                        tenant_id=normalized.tenantId,
                        contract_id=normalized.contractId,
                    )

            except Exception as e:
                print(f"  FAILED: {e}")
                failures.append({
                    "clauseKgId": clause.kgId,
                    "error": str(e),
                })

    finally:
        if writer:
            writer.close()

    output_path = (
        Path(args.output)
        if args.output
        else config.KG_EXTRACTIONS_DIR / f"{normalized.contractId}_legal_extractions.json"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            [r.model_dump() for r in results],
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(json.dumps({
        "contractId": normalized.contractId,
        "selectedClauses": len(selected),
        "successfulExtractions": len(results),
        "failures": failures,
        "dryRun": args.dry_run,
        "output": str(output_path),
        "semanticGraphWritten": not args.dry_run,
    }, indent=2))


if __name__ == "__main__":
    main()