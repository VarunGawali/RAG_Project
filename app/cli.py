import argparse
import json

from app import config
from app.services.ingestion_service import IngestionService
from app.validation.validator import validate_processed_dir


def cmd_ingest_file(args):
    res = IngestionService().ingest_file(
        args.file,
        args.contract_id,
        args.pageindex_json,
    )
    print(json.dumps(res, indent=2))


def cmd_ingest_folder(args):
    res = IngestionService().ingest_folder(
        args.folder,
        args.pageindex_folder,
    )
    print(json.dumps(res, indent=2))


def cmd_validate(args):
    res = validate_processed_dir(args.processed_dir)
    print(json.dumps(res, indent=2))


def cmd_create_search_index(args):
    from app.indexing.azure_search_uploader import AzureSearchIndexer

    indexer = AzureSearchIndexer()

    if args.recreate:
        indexer.delete_index_if_exists()

    indexer.create_or_update_index()

    print(json.dumps({
        "index": indexer.index_name,
        "createdOrUpdated": True,
    }, indent=2))


def cmd_upload_search(args):
    from app.indexing.azure_search_uploader import AzureSearchIndexer

    indexer = AzureSearchIndexer()

    count = indexer.upload_documents_from_file(
        corpus_path=args.index_docs,
        batch_size=args.batch_size,
        kg_path=args.kg_path,
    )

    print(json.dumps({
        "index": indexer.index_name,
        "uploaded": count,
        "indexDocs": args.index_docs,
        "kgPath": args.kg_path,
    }, indent=2))


def cmd_test_search(args):
    from app.indexing.search_tester import AzureSearchTester

    tester = AzureSearchTester()

    results = tester.hybrid_search(
        query=args.query,
        contract_id=args.contract_id,
        top=args.top,
    )

    compact = []

    for r in results:
        compact.append({
            "title": r.get("title"),
            "contractId": r.get("contractId"),
            "pageStart": r.get("pageStart"),
            "pageEnd": r.get("pageEnd"),
            "sourcePath": r.get("sourcePath"),
            "clauseType": r.get("clauseType"),

            # Graph bridge fields
            "kgId": r.get("kgId"),
            "parentKgId": r.get("parentKgId"),
            "graphReady": r.get("graphReady"),
            "nodeType": r.get("nodeType"),
            "graphLabel": r.get("graphLabel"),

            "score": r.get("@search.score"),
            "textPreview": (r.get("text") or "")[:500],
        })

    print(json.dumps(compact, indent=2))


def main():
    parser = argparse.ArgumentParser("contract-ingestion-indexing-poc")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("ingest-file")
    p.add_argument("--file", required=True)
    p.add_argument("--contract-id")
    p.add_argument("--pageindex-json")
    p.set_defaults(func=cmd_ingest_file)

    p = sub.add_parser("ingest-folder")
    p.add_argument("--folder", required=True)
    p.add_argument("--pageindex-folder")
    p.set_defaults(func=cmd_ingest_folder)

    p = sub.add_parser("validate")
    p.add_argument("--processed-dir", default=str(config.PROCESSED_DIR))
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("create-search-index")
    p.add_argument("--recreate", action="store_true")
    p.set_defaults(func=cmd_create_search_index)

    p = sub.add_parser("upload-search")
    p.add_argument(
        "--index-docs",
        default=str(config.PROCESSED_DIR / "corpus_index_docs.json"),
        help="Path to index_docs.json or corpus_index_docs.json",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=500,
    )
    p.add_argument(
        "--kg-path",
        default=None,
        help=(
            "Optional normalized KG JSON path used to enrich search docs "
            "with kgId, parentKgId, graphReady, nodeType, and graphLabel"
        ),
    )
    p.set_defaults(func=cmd_upload_search)

    p = sub.add_parser("test-search")
    p.add_argument("query")
    p.add_argument("--contract-id", default=None)
    p.add_argument("--top", type=int, default=5)
    p.set_defaults(func=cmd_test_search)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()