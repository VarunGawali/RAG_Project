"""
Batch legal extraction — runs run_legal_extraction over every
normalized KG JSON found in --kg-dir (default: data/kg/normalized).
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app import config
from app.kg.models import NormalizedContract
from app.kg.clause_selector import select_representative_clauses
from app.kg.legal_extractor import LegalLLMExtractor
from app.kg.gremlin_writer import GremlinWriter


def process_contract(
    kg_path: Path,
    limit: int,
    dry_run: bool,
    output_dir: Path,
    extractor: LegalLLMExtractor,
    writer,
    workers: int = 8,
) -> dict:
    with open(kg_path, "r", encoding="utf-8") as f:
        normalized = NormalizedContract(**json.load(f))

    selected = select_representative_clauses(normalized.nodes, limit=limit)
    print(f"\n{'='*60}")
    print(f"Contract : {normalized.contractId}")
    print(f"Selected : {len(selected)} clauses")

    results = []
    failures = []

    def extract_one(clause):
        return extractor.extract_from_clause(clause)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_clause = {pool.submit(extract_one, c): c for c in selected}
        for future in as_completed(future_to_clause):
            clause = future_to_clause[future]
            try:
                result = future.result()
                results.append(result)
                print(f"  OK  {clause.kgId} — entities={len(result.entities)} rels={len(result.relationships)}")
                if writer:
                    writer.write_legal_extraction(
                        extraction=result,
                        tenant_id=normalized.tenantId,
                        contract_id=normalized.contractId,
                    )
            except Exception as e:
                print(f"  FAIL {clause.kgId} — {e}")
                failures.append({"clauseKgId": clause.kgId, "error": str(e)})

    output_path = output_dir / f"{normalized.contractId}_legal_extractions.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump([r.model_dump() for r in results], f, indent=2, ensure_ascii=False)

    return {
        "contractId": normalized.contractId,
        "selectedClauses": len(selected),
        "successfulExtractions": len(results),
        "failureCount": len(failures),
        "failures": failures,
        "output": str(output_path),
    }


def main():
    parser = argparse.ArgumentParser("run-legal-extraction-batch")
    parser.add_argument(
        "--kg-dir",
        default=str(config.KG_DIR / "normalized"),
        help="Directory containing normalized KG JSON files",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max clauses per contract (default: all qualifying clauses)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract but do not write to Gremlin",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Parallel LLM calls per contract (default 8)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for extraction JSON outputs (default: data/kg/extractions)",
    )
    args = parser.parse_args()

    kg_dir = Path(args.kg_dir)
    output_dir = Path(args.output_dir) if args.output_dir else config.KG_EXTRACTIONS_DIR

    kg_files = sorted(kg_dir.glob("*.json"))
    if not kg_files:
        print(f"No JSON files found in {kg_dir}")
        return

    print(f"Found {len(kg_files)} contract(s) in {kg_dir}")

    extractor = LegalLLMExtractor()
    writer = None if args.dry_run else GremlinWriter()

    summary = []

    try:
        for kg_path in kg_files:
            try:
                result = process_contract(kg_path, args.limit, args.dry_run, output_dir, extractor, writer, args.workers)
                summary.append(result)
            except Exception as e:
                print(f"  CONTRACT FAILED ({kg_path.name}): {e}")
                summary.append({"contractFile": kg_path.name, "error": str(e)})
    finally:
        if writer:
            writer.close()

    print("\n" + "="*60)
    print("BATCH SUMMARY")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()