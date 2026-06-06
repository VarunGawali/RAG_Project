import os
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)

EMBEDDING_MODEL = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")


def generate_query_embedding(query: str):
    """
    Generate embedding for user query.
    """

    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query
    )

    return response.data[0].embedding