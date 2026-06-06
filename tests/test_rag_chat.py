from agents.semantic_rag_chat_agent import SemanticRAGChatAgent

agent = SemanticRAGChatAgent(
    tree_path="data/edison_tree.json"
)

query = "What environmental reporting obligations exist under the agreement?"

response = agent.ask(
    query=query,
    contract_id="Edison_NYPA_OandM_Contract_1"
)


print("\n========== ANSWER ==========\n")

print(response["answer"])

print("\n========== CITATIONS ==========\n")

for citation in response["citations"]:

    print(citation)
