import os

from dotenv import load_dotenv

from azure.core.credentials import (
    AzureKeyCredential
)

from azure.search.documents import (
    SearchClient
)

load_dotenv()

search_client = SearchClient(
    endpoint=os.getenv(
        "AZURE_SEARCH_ENDPOINT"
    ),

    index_name=os.getenv(
        "AZURE_SEARCH_INDEX"
    ),

    credential=AzureKeyCredential(
        os.getenv("AZURE_SEARCH_KEY")
    )
)
