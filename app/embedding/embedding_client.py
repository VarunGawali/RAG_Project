from typing import List

from app import config
from app.embedding.local_embeddings import local_embedding


class EmbeddingClient:
    def __init__(self):
        self._azure_client = None

    def embed(self, text: str) -> List[float]:
        if config.USE_AZURE_OPENAI_EMBEDDINGS:
            return self._azure_embed(text)

        return local_embedding(text)

    def _azure_embed(self, text: str) -> List[float]:
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

        # Keep input bounded for embedding model limits
        safe_text = text[:24000]

        response = self._azure_client.embeddings.create(
            model=config.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
            input=safe_text,
            dimensions=1536
        )

        return response.data[0].embedding