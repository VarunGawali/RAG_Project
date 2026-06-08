#!/usr/bin/env bash
# =============================================================================
# Contract360 — Azure Container Apps quick-deploy script
#
# Prerequisites:
#   - az CLI logged in:  az login
#   - Docker running
#   - .env file populated from .env.example
#
# Usage:
#   chmod +x deploy-aca.sh
#   ./deploy-aca.sh
#
# The script:
#   1. Creates an Azure Container Registry (if it doesn't exist)
#   2. Builds and pushes the backend + frontend images
#   3. Creates (or updates) two Container Apps — api and ui
#   4. Prints the public URLs when done
# =============================================================================
set -euo pipefail

# ── Configuration — edit these ─────────────────────────────────────────────
RESOURCE_GROUP="${RESOURCE_GROUP:-contract360-rg}"
LOCATION="${LOCATION:-eastus}"
ACR_NAME="${ACR_NAME:-contract360acr}"          # must be globally unique, lowercase
ENVIRONMENT="${ENVIRONMENT:-contract360-env}"   # Container Apps environment name
API_APP="${API_APP:-contract360-api}"
UI_APP="${UI_APP:-contract360-ui}"

# ── Load env vars from .env ─────────────────────────────────────────────────
if [[ -f .env ]]; then
    set -a; source .env; set +a
else
    echo "ERROR: .env file not found. Copy .env.example to .env and fill it in."
    exit 1
fi

echo "==> Creating resource group '$RESOURCE_GROUP' in $LOCATION (idempotent)..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none

echo "==> Creating container registry '$ACR_NAME' (idempotent)..."
az acr create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$ACR_NAME" \
    --sku Basic \
    --admin-enabled true \
    --output none

ACR_LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --query loginServer -o tsv)
ACR_USERNAME=$(az acr credential show --name "$ACR_NAME" --query username -o tsv)
ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --query "passwords[0].value" -o tsv)

echo "==> Building and pushing backend image..."
az acr build \
    --registry "$ACR_NAME" \
    --image "${API_APP}:latest" \
    --file Dockerfile \
    .

echo "==> Creating Container Apps environment (idempotent)..."
az containerapp env create \
    --name "$ENVIRONMENT" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --output none 2>/dev/null || true

echo "==> Deploying API container app..."
az containerapp create \
    --name "$API_APP" \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$ENVIRONMENT" \
    --image "${ACR_LOGIN_SERVER}/${API_APP}:latest" \
    --registry-server "$ACR_LOGIN_SERVER" \
    --registry-username "$ACR_USERNAME" \
    --registry-password "$ACR_PASSWORD" \
    --target-port 8000 \
    --ingress external \
    --min-replicas 1 \
    --max-replicas 5 \
    --cpu 1 --memory 2Gi \
    --env-vars \
        USE_BLOB_ARTIFACTS=true \
        AZURE_OPENAI_ENDPOINT="$AZURE_OPENAI_ENDPOINT" \
        AZURE_OPENAI_API_KEY=secretref:openai-key \
        AZURE_OPENAI_API_VERSION="$AZURE_OPENAI_API_VERSION" \
        AZURE_OPENAI_CHAT_DEPLOYMENT="$AZURE_OPENAI_CHAT_DEPLOYMENT" \
        AZURE_OPENAI_EMBEDDING_DEPLOYMENT="$AZURE_OPENAI_EMBEDDING_DEPLOYMENT" \
        USE_AZURE_OPENAI_EMBEDDINGS="${USE_AZURE_OPENAI_EMBEDDINGS:-true}" \
        AZURE_SEARCH_ENDPOINT="$AZURE_SEARCH_ENDPOINT" \
        AZURE_SEARCH_ADMIN_KEY=secretref:search-key \
        AZURE_SEARCH_INDEX="$AZURE_SEARCH_INDEX" \
        AZURE_BLOB_CONNECTION_STRING=secretref:blob-conn \
        AZURE_BLOB_CONTAINER="$AZURE_BLOB_CONTAINER" \
        COSMOS_NOSQL_ENDPOINT="$COSMOS_NOSQL_ENDPOINT" \
        COSMOS_NOSQL_KEY=secretref:cosmos-key \
        COSMOS_NOSQL_DATABASE="$COSMOS_NOSQL_DATABASE" \
        GREMLIN_ENDPOINT="${GREMLIN_ENDPOINT:-}" \
        GREMLIN_DATABASE="${GREMLIN_DATABASE:-}" \
        GREMLIN_GRAPH="${GREMLIN_GRAPH:-}" \
        GREMLIN_USERNAME="${GREMLIN_USERNAME:-}" \
        GREMLIN_PASSWORD=secretref:gremlin-pw \
        TENANT_ID="${TENANT_ID:-contract360-prod}" \
    --secrets \
        openai-key="${AZURE_OPENAI_API_KEY}" \
        search-key="${AZURE_SEARCH_ADMIN_KEY}" \
        blob-conn="${AZURE_BLOB_CONNECTION_STRING}" \
        cosmos-key="${COSMOS_NOSQL_KEY}" \
        gremlin-pw="${GREMLIN_PASSWORD:-placeholder}" \
    --output none

API_URL=$(az containerapp show \
    --name "$API_APP" \
    --resource-group "$RESOURCE_GROUP" \
    --query "properties.configuration.ingress.fqdn" -o tsv)
API_URL="https://${API_URL}"
echo "==> API deployed at: $API_URL"

echo "==> Building and pushing frontend image (VITE_API_BASE_URL=${API_URL})..."
az acr build \
    --registry "$ACR_NAME" \
    --image "${UI_APP}:latest" \
    --file frontend/Dockerfile \
    --build-arg "VITE_API_BASE_URL=${API_URL}" \
    ./frontend

echo "==> Deploying frontend container app..."
az containerapp create \
    --name "$UI_APP" \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$ENVIRONMENT" \
    --image "${ACR_LOGIN_SERVER}/${UI_APP}:latest" \
    --registry-server "$ACR_LOGIN_SERVER" \
    --registry-username "$ACR_USERNAME" \
    --registry-password "$ACR_PASSWORD" \
    --target-port 80 \
    --ingress external \
    --min-replicas 1 \
    --max-replicas 3 \
    --cpu 0.5 --memory 1Gi \
    --output none

UI_URL=$(az containerapp show \
    --name "$UI_APP" \
    --resource-group "$RESOURCE_GROUP" \
    --query "properties.configuration.ingress.fqdn" -o tsv)
UI_URL="https://${UI_URL}"
echo "==> Frontend deployed at: $UI_URL"

echo "==> Updating ALLOWED_ORIGINS on the API to allow the frontend..."
az containerapp update \
    --name "$API_APP" \
    --resource-group "$RESOURCE_GROUP" \
    --set-env-vars "ALLOWED_ORIGINS=${UI_URL}" \
    --output none

echo ""
echo "======================================================================"
echo "  Contract360 deployed successfully!"
echo "  Frontend : $UI_URL"
echo "  Backend  : $API_URL"
echo "  Health   : ${API_URL}/health"
echo "======================================================================"
