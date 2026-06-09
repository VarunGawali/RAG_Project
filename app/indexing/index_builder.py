from typing import Dict, List
from app.models import Chunk
from app.embedding.embedding_client import EmbeddingClient

class IndexBuilder:
    def __init__(self):
        self.embedder = EmbeddingClient()

    def chunks_to_index_docs(self, chunks: List[Chunk]) -> List[Dict]:
        if not chunks:
            return []

        print(f"[IndexBuilder] Embedding {len(chunks)} chunks in batches…", flush=True)
        texts = [ch.text for ch in chunks]
        embeddings = self.embedder.embed_many(texts)

        docs = []
        for ch, emb in zip(chunks, embeddings):
            ch.embedding = emb
            docs.append(ch.to_dict())

        print(f"[IndexBuilder] Done — {len(docs)} docs ready.", flush=True)
        return docs
    

