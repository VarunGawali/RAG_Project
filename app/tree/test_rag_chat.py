from agents.semantic_rag_chat_agent import SemanticRAGChatAgent

agent = SemanticRAGChatAgent(
    corpus_path="data/corpus_index_docs.json",
    tree_path="data/tree.json"
)

query = "Can the customer terminate the agreement early?"

response = agent.ask(
    query=query,
    contract_id="Terra-Gen_SJCE__PPA__PUBLIC_1"
)


print("\n========== ANSWER ==========\n")

print(response["answer"])

print("\n========== CITATIONS ==========\n")

for citation in response["citations"]:

    print(citation)