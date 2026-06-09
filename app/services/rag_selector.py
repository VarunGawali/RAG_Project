from app.tree.tree_chat import SemanticRAGChatAgent as TreeRAGAgent
from app.kg.graph_chat import graph_rag_chat as GraphRAGAgent

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
            self.agent = None  # Initialize GraphRAGAgent
        
    def ask(self, query: str, contract_id: str = None):
        if self.approach == "tree":
            return self.agent.ask(query=query, contract_id=contract_id)
        elif self.approach == "graph":
            # Call graph RAG
            pass
