import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
SAMPLES_DIR = ROOT / "samples"

PAGEINDEX_OUTPUT_DIR = ROOT / "samples" / "pageindex_trees"

# KG output folders
KG_DIR = DATA_DIR / "kg"
KG_NORMALIZED_DIR = KG_DIR / "normalized"
KG_EXTRACTIONS_DIR = KG_DIR / "extractions"
KG_LOGS_DIR = KG_DIR / "logs"

# Ensure KG folders exist
KG_NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
KG_EXTRACTIONS_DIR.mkdir(parents=True, exist_ok=True)
KG_LOGS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------
# Azure Document Intelligence
# ---------------------------------------------------------------------

USE_AZURE_DOCUMENT_INTELLIGENCE = (
    os.getenv("USE_AZURE_DOCUMENT_INTELLIGENCE", "false").lower() == "true"
)

AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
AZURE_DOCUMENT_INTELLIGENCE_KEY = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY")


# ---------------------------------------------------------------------
# Azure OpenAI / Azure AI Foundry
# Shared endpoint/key used for both chat + embeddings
# ---------------------------------------------------------------------

USE_AZURE_OPENAI_EMBEDDINGS = (
    os.getenv("USE_AZURE_OPENAI_EMBEDDINGS", "false").lower() == "true"
)

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

# Chat model deployment, e.g. gpt-4-1-mini
AZURE_OPENAI_CHAT_DEPLOYMENT = os.getenv(
    "AZURE_OPENAI_CHAT_DEPLOYMENT",
    "gpt-4-1-mini"
)

# Embedding model deployment, e.g. text-embedding-3-small
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = os.getenv(
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    "text-embedding-3-small"
)


# ---------------------------------------------------------------------
# PageIndex API integration
# ---------------------------------------------------------------------

USE_PAGEINDEX_API = os.getenv("USE_PAGEINDEX_API", "false").lower() == "true"
PAGEINDEX_API_KEY = os.getenv("PAGEINDEX_API_KEY")
PAGEINDEX_POLL_SECONDS = int(os.getenv("PAGEINDEX_POLL_SECONDS", "10"))
PAGEINDEX_MAX_POLLS = int(os.getenv("PAGEINDEX_MAX_POLLS", "60"))


# ---------------------------------------------------------------------
# Azure AI Search
# ---------------------------------------------------------------------

AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_ADMIN_KEY = os.getenv("AZURE_SEARCH_ADMIN_KEY")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX", "contract-knowledge-index")
AZURE_SEARCH_VECTOR_DIMENSIONS = int(os.getenv("AZURE_SEARCH_VECTOR_DIMENSIONS", "1536"))


# ---------------------------------------------------------------------
# Azure Blob Storage (raw file + artifact persistence)
# ---------------------------------------------------------------------

AZURE_BLOB_CONNECTION_STRING = os.getenv("AZURE_BLOB_CONNECTION_STRING", "")
AZURE_BLOB_CONTAINER = os.getenv("AZURE_BLOB_CONTAINER", "contract360-artifacts")


# ---------------------------------------------------------------------
# Cosmos DB NoSQL (chat history)
# ---------------------------------------------------------------------

COSMOS_NOSQL_ENDPOINT = os.getenv("COSMOS_NOSQL_ENDPOINT")
COSMOS_NOSQL_KEY = os.getenv("COSMOS_NOSQL_KEY")
COSMOS_NOSQL_DATABASE = os.getenv("COSMOS_NOSQL_DATABASE", "contract360")


# ---------------------------------------------------------------------
# Cosmos DB for Apache Gremlin
# ---------------------------------------------------------------------

GREMLIN_ENDPOINT = os.getenv("GREMLIN_ENDPOINT")
GREMLIN_DATABASE = os.getenv("GREMLIN_DATABASE")
GREMLIN_GRAPH = os.getenv("GREMLIN_GRAPH")
GREMLIN_USERNAME = os.getenv("GREMLIN_USERNAME")
GREMLIN_PASSWORD = os.getenv("GREMLIN_PASSWORD")

# Application-level tenant/workspace id.
# This is used as the value of the Gremlin partition key /pk.
# It is NOT necessarily your Azure tenant id.
TENANT_ID = os.getenv("TENANT_ID", "contract360-dev")


# ---------------------------------------------------------------------
# Chunking / embeddings defaults
# ---------------------------------------------------------------------

LOCAL_EMBEDDING_DIM = 256
CHUNK_MAX_WORDS = 850
CHUNK_OVERLAP_WORDS = 80


# ---------------------------------------------------------------------
# KG extraction defaults
# ---------------------------------------------------------------------

KG_EXTRACTION_LIMIT = int(os.getenv("KG_EXTRACTION_LIMIT", "20"))
KG_MIN_CLAUSE_CHARS = int(os.getenv("KG_MIN_CLAUSE_CHARS", "80"))
KG_MAX_CLAUSE_CHARS = int(os.getenv("KG_MAX_CLAUSE_CHARS", "3000"))

# If true, legal extraction runs but does not write semantic entities/edges to Gremlin.
KG_DRY_RUN = os.getenv("KG_DRY_RUN", "false").lower() == "true"