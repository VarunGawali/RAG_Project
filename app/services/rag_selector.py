from app.tree.tree_rag_chat import SemanticRAGChatAgent as TreeRAGAgent
from app.rag.chat import graph_rag_chat as GraphRAGAgent

class UnifiedRAGSelector:
    """
    Unified interface to switch between Tree-RAG and Graph-RAG approaches.
    Used for comparison studies.
    """
    
    def __init__(self, approach: str = "tree"):
        self.approach = approach
        
        if approach == "tree":
            self.agent = TreeRAGAgent(
                corpus_path="data/corpus_index_docs.json",
                tree_path="data/tree.json"
            )
        elif approach == "graph":
            self.agent = GraphRAGAgent(
                corpus_path="data/corpus_index_docs.json"
            )
        
    def ask(self, query: str, contract_id: str = None):
        if self.approach == "tree":
            return self.agent.ask(query=query, contract_id=contract_id)
        elif self.approach == "graph":
            # Call graph RAG
            return self.agent.ask(query=query, contract_id=contract_id)
