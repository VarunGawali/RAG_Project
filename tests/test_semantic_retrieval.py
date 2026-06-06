from core.ai_assistant.semantic_retriever import SemanticRetriever


CORPUS_PATH = "data/corpus_index_docs.json"

TREE_PATH = (
    "data/tree.json"
)

retriever = SemanticRetriever(
    corpus_path=CORPUS_PATH,
    tree_path=TREE_PATH
)

query = "Can the customer terminate the agreement early?"

results = retriever.retrieve(
    query=query,
    top_k=3,
    contract_id="Terra-Gen_SJCE__PPA__PUBLIC_1"
)

print("\n========== TOP RESULTS ==========\n")

for i, result in enumerate(results, start=1):

    print(f"\nRESULT {i}")
    print("=" * 60)

    print(f"Score: {result['score']:.4f}")
    print(f"Contract: {result['contractId']}")
    print(f"Section: {result['sectionTitle']}")
    print(f"Clause Type: {result['clauseType']}")
    print(f"Pages: {result['pageStart']} - {result['pageEnd']}")

    print("\nTEXT:")
    print(result["text"][:1000])

    # -----------------------------------------
    # TREE EXPANSION
    # -----------------------------------------

    print("\n========== EXPANDED CONTEXT ==========")

    expanded_nodes = result.get(
        "contextExpansion",
        []
    )

    for node in expanded_nodes:

        print("\n--- NODE ---")

        print(
            f"Node ID: {node.get('nodeId')}"
        )

        print(
            f"Title: {node.get('title')}"
        )

        print(
            f"Node Type: {node.get('nodeType')}"
        )

        
        # if node.get("text"):

        #     print("\nTEXT PREVIEW:")

        #     print(
        #         node.get("text")[:300]
        #     )
        