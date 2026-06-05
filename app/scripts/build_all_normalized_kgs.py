from pathlib import Path
import subprocess
import sys


PROCESSED_DIR = Path("data/processed")
NORMALIZED_KG_DIR = Path("data/kg/normalized")


def main():
    NORMALIZED_KG_DIR.mkdir(parents=True, exist_ok=True)

    tree_paths = sorted(PROCESSED_DIR.glob("*/tree.json"))

    if not tree_paths:
        print(f"No tree.json files found under {PROCESSED_DIR}")
        return

    print(f"Found {len(tree_paths)} tree.json files")

    success = 0
    failed = 0
    skipped = 0

    for tree_path in tree_paths:
        contract_id = tree_path.parent.name

        # Skip non-contract/corpus folders if any are present.
        if contract_id.startswith("corpus"):
            skipped += 1
            continue

        expected_output = NORMALIZED_KG_DIR / f"{contract_id}_kg_ready.json"

        print("\n" + "=" * 80)
        print(f"Building normalized KG for: {contract_id}")
        print(f"Tree: {tree_path}")
        print(f"Expected output: {expected_output}")

        cmd = [
            sys.executable,
            "-m",
            "app.scripts.build_structural_kg",
            "--tree",
            str(tree_path),
            "--skip-gremlin",
        ]

        try:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
            )

            if result.stdout:
                print(result.stdout)

            if result.stderr:
                print(result.stderr)

            if result.returncode == 0 and expected_output.exists():
                print(f"Created: {expected_output}")
                success += 1
            elif result.returncode == 0:
                print(
                    "Command succeeded, but expected output was not found: "
                    f"{expected_output}"
                )
                failed += 1
            else:
                print(f"Failed for {contract_id}")
                failed += 1

        except Exception as exc:
            print(f"Exception while processing {contract_id}: {exc}")
            failed += 1

    print("\n" + "=" * 80)
    print("Normalized KG build complete")
    print(f"Success: {success}")
    print(f"Failed : {failed}")
    print(f"Skipped: {skipped}")


if __name__ == "__main__":
    main()
