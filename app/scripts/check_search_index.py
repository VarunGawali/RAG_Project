from collections import Counter

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

from app import config


def main():
    client = SearchClient(
        endpoint=config.AZURE_SEARCH_ENDPOINT,
        index_name=config.AZURE_SEARCH_INDEX,
        credential=AzureKeyCredential(config.AZURE_SEARCH_ADMIN_KEY),
    )

    results = client.search(
        search_text="*",
        select=[
            "id",
            "contractId",
            "kgId",
            "graphReady",
            "nodeType",
            "graphLabel",
            "title",
        ],
        top=1000,
        include_total_count=True,
    )

    docs = [dict(r) for r in results]

    print("Total count reported:", results.get_count())
    print("Docs fetched:", len(docs))

    print("\nContracts:")
    print(Counter(d.get("contractId") for d in docs))

    print("\nGraph ready:")
    print(Counter(d.get("graphReady") for d in docs))

    print("\nNode types:")
    print(Counter(d.get("nodeType") for d in docs))

    print("\nGraph labels:")
    print(Counter(d.get("graphLabel") for d in docs))

    print("\nSample docs:")
    for d in docs[:5]:
        print({
            "id": d.get("id"),
            "contractId": d.get("contractId"),
            "kgId": d.get("kgId"),
            "graphReady": d.get("graphReady"),
            "nodeType": d.get("nodeType"),
            "graphLabel": d.get("graphLabel"),
            "title": d.get("title"),
        })


if __name__ == "__main__":
    main()