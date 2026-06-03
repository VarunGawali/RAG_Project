import os
import json

from dotenv import load_dotenv

from langchain_openai import AzureChatOpenAI
from langchain_neo4j import Neo4jGraph

from langchain_experimental.graph_transformers import (
    LLMGraphTransformer
)

from langchain_core.documents import Document

load_dotenv()


# ---------------------------------------------------
# LOAD TREE JSON
# ---------------------------------------------------

TREE_PATH = (
    "data/tree.json"
)

with open(TREE_PATH, "r", encoding="utf-8") as f:
    tree_data = json.load(f)


# ---------------------------------------------------
# RECURSIVE NODE EXTRACTION
# ---------------------------------------------------

valid_nodes = []


def traverse_tree(node):

    node_type = node.get("nodeType")

    # -----------------------------------------
    # KEEP CLAUSE + SECTION NODES
    # -----------------------------------------

    if node_type in ["clause", "section"]:

        text = node.get("text", "")

        if text.strip():

            valid_nodes.append(node)

    # -----------------------------------------
    # RECURSIVELY VISIT CHILDREN
    # -----------------------------------------

    children = node.get("children", [])

    for child in children:
        traverse_tree(child)


# Start traversal from root
traverse_tree(tree_data)


print(f"\nLoaded valid nodes: {len(valid_nodes)}")


# ---------------------------------------------------
# LIMIT INITIAL TEST SIZE
# ---------------------------------------------------

sample_nodes = valid_nodes[:5]

print(
    f"\nTesting on {len(sample_nodes)} nodes..."
)


# ---------------------------------------------------
# CONVERT TO LANGCHAIN DOCUMENTS
# ---------------------------------------------------

documents = []

for node in sample_nodes:

    documents.append(
        Document(
            page_content=node.get("text"),
            metadata={
                "nodeId": node.get("nodeId"),
                "title": node.get("title"),
                "nodeType": node.get("nodeType"),
                "pageStart": node.get("pageStart"),
                "pageEnd": node.get("pageEnd")
            }
        )
    )


# ---------------------------------------------------
# INITIALIZE AZURE OPENAI
# ---------------------------------------------------

llm = AzureChatOpenAI(
    azure_deployment=os.getenv(
        "AZURE_OPENAI_LLM_DEPLOYMENT"
    ),
    api_version=os.getenv(
        "AZURE_OPENAI_API_VERSION"
    ),
    azure_endpoint=os.getenv(
        "AZURE_OPENAI_ENDPOINT"
    ),
    api_key=os.getenv(
        "AZURE_OPENAI_API_KEY"
    ),
    temperature=0
)



# ---------------------------------------------------
# INITIALIZE GRAPH TRANSFORMER
# ---------------------------------------------------

llm_transformer = LLMGraphTransformer(
    llm=llm
)


# ---------------------------------------------------
# GENERATE GRAPH DOCUMENTS
# ---------------------------------------------------



graph = Neo4jGraph(
    url=os.getenv(
        "NEO4J_URI"
    ),
    username=os.getenv(
        "NEO4J_USERNAME"
    ),
    password=os.getenv(
        "NEO4J_PASSWORD"
    )
)


graph_documents = (
    llm_transformer.convert_to_graph_documents(
        documents
    )
)


graph.add_graph_documents(
    graph_documents
)



# ---------------------------------------------------
# PRINT RESULTS
# ---------------------------------------------------

for i, graph_doc in enumerate(
    graph_documents,
    start=1
):

    source_node = sample_nodes[i - 1]

    print("\n" + "=" * 80)
    print(f"GRAPH DOCUMENT {i}")
    print("=" * 80)

    print("\nSOURCE NODE:\n")

    print({
        "nodeId": source_node.get("nodeId"),
        "title": source_node.get("title"),
        "nodeType": source_node.get("nodeType")
    })

    print("\nNODES:\n")

    for node in graph_doc.nodes:

        print({
            "id": node.id,
            "type": node.type,
            "properties": node.properties
        })

    print("\nRELATIONSHIPS:\n")

    for rel in graph_doc.relationships:

        print({
            "source": rel.source.id,
            "target": rel.target.id,
            "type": rel.type,
            "properties": rel.properties
        })