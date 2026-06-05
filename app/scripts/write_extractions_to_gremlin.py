"""
Stage 3b: Write saved extraction JSONs to Cosmos Gremlin.

Reads extraction JSONs produced by run_legal_extraction_batch --dry-run
and writes them to Gremlin with a configurable delay between clauses
to stay within free-tier RU limits (default 1000 RU/s).

Usage:
    python -m app.scripts.write_extractions_to_gremlin
    python -m app.scripts.write_extractions_to_gremlin --delay 1.5
    python -m app.scripts.write_extractions_to_gremlin --extractions-dir data/kg/extractions
"""

import argparse
import json
import time
from pathlib import Path

from app import config
from app.kg.models import LegalExtractionResult
from app.kg.gremlin_writer import GremlinWriter


def main():
    parser = argparse.ArgumentParser("write-extractions-to-gremlin")
    parser.add_argument(
        "--extractions-dir",
        default=str(config.KG_EXTRACTIONS_DIR),
        help="Directory containing *_legal_extractions.json files",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds to sleep between clauses (default 1.0 — safe for 1000 RU free tier)",
    )
    parser.add_argument(
        "--tenant-id",
        default=config.TENANT_ID if hasattr(config, "TENANT_ID") else "default",
        help="Tenant ID to tag vertices with",
    )
    args = parser.parse_args()

    extractions_dir = Path(args.extractions_dir)
    files = sorted(extractions_dir.glob("*_legal_extractions.json"))

    if not files:
        print(f"No extraction files found in {extractions_dir}")
        return

    print(f"Found {len(files)} extraction file(s)")

    writer = GremlinWriter()

    try:
        for extraction_file in files:
            contract_id = extraction_file.stem.replace("_legal_extractions", "")
            print(f"\n{'='*60}")
            print(f"Writing: {contract_id}")

            with open(extraction_file, "r", encoding="utf-8") as f:
                raw = json.load(f)

            extractions = [LegalExtractionResult(**r) for r in raw]
            print(f"Clauses: {len(extractions)}")

            for idx, extraction in enumerate(extractions, start=1):
                print(f"  [{idx}/{len(extractions)}] {extraction.source_clause_id} "
                      f"— {len(extraction.entities)} entities, {len(extraction.relationships)} rels")
                try:
                    writer.write_legal_extraction(
                        extraction=extraction,
                        tenant_id=args.tenant_id,
                        contract_id=contract_id,
                    )
                except Exception as e:
                    print(f"    ERROR: {e}")

                if args.delay > 0:
                    time.sleep(args.delay)

    finally:
        writer.close()

    print("\nDone.")


if __name__ == "__main__":
    main()