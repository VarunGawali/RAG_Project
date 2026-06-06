import argparse
import json
from pathlib import Path

from app.kg.normalize_tree import (
    normalize_contract_tree,
    save_normalized_contract,
    default_normalized_output_path,
)
from app.kg.gremlin_writer import GremlinWriter


def main():
    parser = argparse.ArgumentParser("build-structural-kg")
    parser.add_argument("--tree", required=True, help="Path to parsed tree JSON")
    parser.add_argument("--output", default=None, help="Optional normalized output path")
    parser.add_argument(
        "--skip-gremlin",
        action="store_true",
        help="Only normalize; do not write to Gremlin",
    )

    args = parser.parse_args()

    normalized = normalize_contract_tree(args.tree)

    output_path = (
        Path(args.output)
        if args.output
        else default_normalized_output_path(normalized.contractId)
    )

    save_normalized_contract(normalized, str(output_path))

    if not args.skip_gremlin:
        writer = GremlinWriter()
        try:
            writer.write_structural_graph(normalized)
        finally:
            writer.close()

    print(json.dumps({
        "contractId": normalized.contractId,
        "tenantId": normalized.tenantId,
        "nodes": len(normalized.nodes),
        "edges": len(normalized.edges),
        "normalizedOutput": str(output_path),
        "gremlinWritten": not args.skip_gremlin,
    }, indent=2))


if __name__ == "__main__":
    main()