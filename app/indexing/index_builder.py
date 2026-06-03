from typing import Dict, List
from app.models import Chunk
from app.embedding.embedding_client import EmbeddingClient

class IndexBuilder:
    def __init__(self):
        self.embedder = EmbeddingClient()

    def chunks_to_index_docs(self, chunks: List[Chunk]) -> List[Dict]:
        docs = []
        for ch in chunks:
            ch.embedding = self.embedder.embed(ch.text)
            docs.append(ch.to_dict())
        return docs
