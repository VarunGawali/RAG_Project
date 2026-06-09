# Deploy Contract360 to Azure Container Apps

## Prerequisites

```bash
# Install Azure CLI if not already installed
# https://learn.microsoft.com/en-us/cli/azure/install-azure-cli

az login
az extension add --name containerapp --upgrade
docker --version   # must be running
```

---

## Step 1 — Clone and configure environment

```bash
git clone https://github.com/VarunGawali/RAG_Project_EY.git
cd RAG_Project_EY

cp .env.example .env
# Open .env and fill in all values marked REQUIRED
```

### Required values in `.env`

| Variable | Where to find it |
|---|---|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI → Keys and Endpoint |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI → Keys and Endpoint |
| `AZURE_OPENAI_API_VERSION` | e.g. `2024-02-01` |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | Azure OpenAI → Deployments (your GPT-4o name) |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Azure OpenAI → Deployments (your embedding model name) |
| `AZURE_SEARCH_ENDPOINT` | Azure AI Search → Overview |
| `AZURE_SEARCH_ADMIN_KEY` | Azure AI Search → Keys |
| `AZURE_SEARCH_INDEX` | Any name, e.g. `contract360` |
| `AZURE_BLOB_CONNECTION_STRING` | Storage Account → Access keys |
| `AZURE_BLOB_CONTAINER` | e.g. `contract360` |
| `COSMOS_NOSQL_ENDPOINT` | Cosmos DB → Overview |
| `COSMOS_NOSQL_KEY` | Cosmos DB → Keys |
| `COSMOS_NOSQL_DATABASE` | e.g. `contract360` |
| `GREMLIN_ENDPOINT` | Cosmos DB (Gremlin API) → Overview |
| `GREMLIN_USERNAME` | `/dbs/<db>/colls/<graph>` |
| `GREMLIN_PASSWORD` | Cosmos DB → Keys → PRIMARY KEY |

---

## Step 2 — Run the one-shot deploy script

```bash
chmod +x deploy-aca.sh
./deploy-aca.sh
```

The script does everything automatically:

1. Creates a Resource Group, Azure Container Registry, and Container Apps Environment
2. Builds and pushes the **backend** image via ACR (no local Docker needed)
3. Deploys the **API** Container App with all secrets wired up
4. Captures the live API URL, uses it to build the **frontend** image with `VITE_API_BASE_URL` baked in
5. Deploys the **frontend** Container App
6. Sets `ALLOWED_ORIGINS` on the API to the frontend URL (CORS auto-wired)
7. Prints both public URLs when done

---

## Step 3 — Create the Azure Search index (first deploy only)

```bash
# With your .env populated, run once after deploy:
python -m app.scripts.check_search_index
# If the index doesn't exist yet, the first document upload from the UI will create it.
```

---

## Step 4 — Verify

```bash
# Health check
curl https://<your-api-url>/health

# Open the frontend
open https://<your-ui-url>
```

---

## Updating after code changes

```bash
# Re-run the script — it uses `az containerapp update` which is idempotent
./deploy-aca.sh
```

Or to update only one side:

```bash
# Backend only
az acr build --registry contract360acr --image contract360-api:latest --file Dockerfile .
az containerapp update --name contract360-api --resource-group contract360-rg \
    --image contract360acr.azurecr.io/contract360-api:latest

# Frontend only (need the API URL first)
API_URL=$(az containerapp show --name contract360-api --resource-group contract360-rg \
    --query "properties.configuration.ingress.fqdn" -o tsv)
az acr build --registry contract360acr --image contract360-ui:latest \
    --file frontend/Dockerfile --build-arg "VITE_API_BASE_URL=https://${API_URL}" ./frontend
az containerapp update --name contract360-ui --resource-group contract360-rg \
    --image contract360acr.azurecr.io/contract360-ui:latest
```

---

## Cost estimate (minimal setup)

| Resource | SKU | Approx. monthly |
|---|---|---|
| Container Apps (API + UI, min 1 replica) | Consumption | ~$15–30 |
| Azure Container Registry | Basic | ~$5 |
| Azure AI Search | Basic (1 replica) | ~$75 |
| Azure OpenAI | Pay-per-token | ~$10–50 depending on usage |
| Cosmos DB (NoSQL + Gremlin) | Serverless | ~$5–15 |
| Blob Storage | LRS | ~$1–5 |
