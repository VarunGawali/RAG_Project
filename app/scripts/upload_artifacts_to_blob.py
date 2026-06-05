"""
One-time migration script: upload pre-built local artifacts to Azure Blob Storage.

Uploads:
  1. /data/kg/normalized/*_kg_ready.json
     → artifacts/<contractId>/kg_normalized.json

  2. /data/processed/<contractId>/tree.json  (if present)
     → artifacts/<contractId>/tree.json

  3. /data/processed/<contractId>/index_docs.json  (if present)
     → artifacts/<contractId>/index_docs.json

  4. /data/processed/<contractId>/chunks.json  (if present)
     → artifacts/<contractId>/chunks.json

  5. /data/processed/<contractId>/manifest.json  (if present)
     → artifacts/<contractId>/manifest.json

Run once after setting AZURE_BLOB_CONNECTION_STRING and AZURE_BLOB_CONTAINER:
    python -m app.scripts.upload_artifacts_to_blob
"""

import json
import sys
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app import config
from app.storage.blob_store import BlobStore


def upload_kg_normalized(blob: BlobStore) -> int:
    uploaded = 0
    for kg_file in sorted(config.KG_NORMALIZED_DIR.glob("*_kg_ready.json")):
        # Derive contractId: strip the _kg_ready suffix
        contract_id = kg_file.stem.removesuffix("_kg_ready")
        try:
            data = json.loads(kg_file.read_text(encoding="utf-8"))
            blob.upload_artifact(contract_id, "kg_normalized.json", data)
            print(f"  ✓ KG normalized: {contract_id}")
            uploaded += 1
        except Exception as exc:
            print(f"  ✗ Failed for {kg_file.name}: {exc}")
    return uploaded


def upload_processed_artifacts(blob: BlobStore) -> int:
    uploaded = 0
    if not config.PROCESSED_DIR.exists():
        print("  (no /data/processed directory found — skipping)")
        return 0

    artifact_names = ["tree.json", "index_docs.json", "chunks.json", "manifest.json"]

    for contract_dir in sorted(config.PROCESSED_DIR.iterdir()):
        if not contract_dir.is_dir():
            continue
        contract_id = contract_dir.name
        for artifact_name in artifact_names:
            path = contract_dir / artifact_name
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                blob.upload_artifact(contract_id, artifact_name, data)
                print(f"  ✓ {contract_id}/{artifact_name}")
                uploaded += 1
            except Exception as exc:
                print(f"  ✗ Failed {contract_id}/{artifact_name}: {exc}")
    return uploaded


def main():
    print("=" * 60)
    print("Contract360 — Artifact Migration to Azure Blob Storage")
    print("=" * 60)
    print(f"Container : {config.AZURE_BLOB_CONTAINER}")
    print()

    if not config.AZURE_BLOB_CONNECTION_STRING:
        print("ERROR: AZURE_BLOB_CONNECTION_STRING is not set.")
        sys.exit(1)

    blob = BlobStore()
    blob.ensure_container()

    print("Uploading KG normalized JSONs...")
    kg_count = upload_kg_normalized(blob)
    print(f"  → {kg_count} KG files uploaded.")
    print()

    print("Uploading processed contract artifacts...")
    artifact_count = upload_processed_artifacts(blob)
    print(f"  → {artifact_count} artifact files uploaded.")
    print()

    print("Migration complete.")


if __name__ == "__main__":
    main()
