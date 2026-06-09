from typing import List

from app import config
from app.embedding.local_embeddings import local_embedding

# Azure OpenAI embeddings API limit per request
_AZURE_BATCH_LIMIT = 16


class EmbeddingClient:
    def __init__(self):
        self._azure_client = None

    def embed(self, text: str) -> List[float]:
        if config.USE_AZURE_OPENAI_EMBEDDINGS:
            return self._azure_embed_many([text])[0]
        return local_embedding(text)

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of texts, batching API calls to stay within limits."""
        if not texts:
            return []
        if config.USE_AZURE_OPENAI_EMBEDDINGS:
            return self._azure_embed_many(texts)
        return [local_embedding(t) for t in texts]

    def _azure_embed_many(self, texts: List[str]) -> List[List[float]]:
        if not config.AZURE_OPENAI_ENDPOINT:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT missing")
        if not config.AZURE_OPENAI_API_KEY:
            raise RuntimeError("AZURE_OPENAI_API_KEY missing")
        if not config.AZURE_OPENAI_EMBEDDING_DEPLOYMENT:
            raise RuntimeError("AZURE_OPENAI_EMBEDDING_DEPLOYMENT missing")

        from openai import AzureOpenAI

        if self._azure_client is None:
            self._azure_client = AzureOpenAI(
                azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
                api_key=config.AZURE_OPENAI_API_KEY,
                api_version=config.AZURE_OPENAI_API_VERSION,
            )

        results: List[List[float]] = []
        safe_texts = [t[:24000] for t in texts]

        for i in range(0, len(safe_texts), _AZURE_BATCH_LIMIT):
            batch = safe_texts[i : i + _AZURE_BATCH_LIMIT]
            response = self._azure_client.embeddings.create(
                model=config.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
                input=batch,
                dimensions=1536,
            )
            # API returns embeddings in the same order as input
            results.extend(item.embedding for item in response.data)

        return results
