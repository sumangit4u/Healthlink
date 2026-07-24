#!/usr/bin/env bash
# ============================================================================
# deploy.sh - ONE-SHOT deploy of the 7-service HealthLink stack to Azure
# Container Apps (macOS / Linux / Git-Bash on Windows).
#
#   streamlit    -> public UI        (--ingress external)
#   api-gateway  -> public gateway   (--ingress external)
#   orchestrator -> internal only    (--ingress internal)
#   symptom / doctor / scheduling / summary agents -> internal only
#
# Everything goes in ONE resource group so teardown.sh deletes it all at once.
# GEMINI_API_KEY (or GEMINI_API_KEY_Orig) and PINECONE_API_KEY are read from the
# shared project .env and injected as Container App secrets. Gemini + Pinecone
# stay as the model/vector providers; only the *hosting* is Azure.
#
# Prereqs: Azure CLI (`az`), a subscription, and `az login` already done.
# Usage:   ./deploy.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- Config (cheap by design - scale-to-zero everywhere) ----
RESOURCE_GROUP="healthlink-rg"
LOCATION="centralindia"                 # pick a region near your users
ACR_NAME="healthlinkacr$RANDOM"         # must be globally unique
ENV_NAME="healthlink-env"
ENV_FILE="$SCRIPT_DIR/../../Module 2 - RAG/.env"   # shared secrets file (coding_ninja/Module 2 - RAG/.env)

# App names + their container ports
STREAMLIT_APP="healthlink-streamlit";   STREAMLIT_PORT=8501
API_APP="healthlink-api";               API_PORT=8000
ORCH_APP="healthlink-orchestrator";     ORCH_PORT=8001
SYMPTOM_APP="healthlink-symptom";       SYMPTOM_PORT=8010
DOCTOR_APP="healthlink-doctor";         DOCTOR_PORT=8011
SCHEDULING_APP="healthlink-scheduling"; SCHEDULING_PORT=8012
SUMMARY_APP="healthlink-summary";       SUMMARY_PORT=8013

# ---- Read the model keys from the shared .env ----
[ -f "$ENV_FILE" ] || { echo "Cannot find shared secrets file: $ENV_FILE"; exit 1; }
read_key() { grep -E "^\s*$1\s*=" "$ENV_FILE" | head -1 | cut -d'=' -f2- | tr -d '"'"'"' '; }
GEMINI_KEY="$(read_key GEMINI_API_KEY)"
[ -n "$GEMINI_KEY" ] || GEMINI_KEY="$(read_key GEMINI_API_KEY_Orig)"
PINECONE_KEY="$(read_key PINECONE_API_KEY)"
[ -n "$GEMINI_KEY" ]   || { echo "GEMINI_API_KEY (or _Orig) not found in $ENV_FILE"; exit 1; }
[ -n "$PINECONE_KEY" ] || { echo "PINECONE_API_KEY not found in $ENV_FILE"; exit 1; }

echo "==> Ensuring containerapp extension + providers..."
az extension add --name containerapp --upgrade --only-show-errors >/dev/null
az provider register --namespace Microsoft.App --wait --only-show-errors >/dev/null
az provider register --namespace Microsoft.OperationalInsights --wait --only-show-errors >/dev/null
az provider register --namespace Microsoft.ContainerRegistry --wait --only-show-errors >/dev/null

echo "==> [1/6] Resource group ($RESOURCE_GROUP in $LOCATION)..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --only-show-errors >/dev/null

echo "==> [2/6] Container Registry ($ACR_NAME, Basic SKU)..."
az acr create --resource-group "$RESOURCE_GROUP" --name "$ACR_NAME" --sku Basic \
    --admin-enabled true --only-show-errors >/dev/null

# Build one image from the repo root using that service's Dockerfile.
build_image() {
    local image="$1" dockerfile="$2"
    echo "    building $image ($dockerfile) ..."
    if ! az acr build --registry "$ACR_NAME" --image "$image" \
            --file "$dockerfile" "$SCRIPT_DIR" --only-show-errors; then
        # ACR Tasks is blocked on free-trial / Azure-for-Students subscriptions
        # (TasksOperationsNotAllowed) - fall back to a local Docker build + push.
        echo "!! Cloud build failed for $image - falling back to local Docker build + push."
        command -v docker >/dev/null || { echo "Docker not found. Start Docker Desktop and rerun."; exit 1; }
        az acr login --name "$ACR_NAME"
        docker build --platform linux/amd64 -t "$ACR_NAME.azurecr.io/$image" \
            -f "$SCRIPT_DIR/$dockerfile" "$SCRIPT_DIR"
        docker push "$ACR_NAME.azurecr.io/$image"
    fi
}

echo "==> [3/6] Building all 7 images in the cloud (az acr build -> amd64)..."
build_image "healthlink-streamlit:latest"    "services/streamlit/Dockerfile"
build_image "healthlink-api:latest"          "services/api_gateway/Dockerfile"
build_image "healthlink-orchestrator:latest" "services/orchestrator/Dockerfile"
build_image "healthlink-symptom:latest"      "services/symptom_agent/Dockerfile"
build_image "healthlink-doctor:latest"       "services/doctor_agent/Dockerfile"
build_image "healthlink-scheduling:latest"   "services/scheduling_agent/Dockerfile"
build_image "healthlink-summary:latest"      "services/summary_agent/Dockerfile"

echo "==> [4/6] Container Apps environment ($ENV_NAME)..."
az containerapp env create --name "$ENV_NAME" --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" --only-show-errors >/dev/null

ACR_SERVER="$ACR_NAME.azurecr.io"
ACR_USER="$(az acr credential show --name "$ACR_NAME" --query username -o tsv)"
ACR_PASS="$(az acr credential show --name "$ACR_NAME" --query 'passwords[0].value' -o tsv)"

# Helper: create an internal agent app with the Gemini secret (+ extra env vars).
create_agent() {
    local app="$1" image="$2" port="$3"; shift 3
    echo "    deploying $app (internal)..."
    az containerapp create \
        --name "$app" --resource-group "$RESOURCE_GROUP" --environment "$ENV_NAME" \
        --image "$ACR_SERVER/$image" \
        --registry-server "$ACR_SERVER" --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
        --target-port "$port" --ingress internal \
        --min-replicas 0 --max-replicas 3 --cpu 0.5 --memory 1.0Gi \
        --secrets "gemini-api-key=$GEMINI_KEY" "pinecone-api-key=$PINECONE_KEY" \
        --env-vars "GEMINI_API_KEY=secretref:gemini-api-key" "PINECONE_API_KEY=secretref:pinecone-api-key" "$@" \
        --only-show-errors >/dev/null
}

echo "==> [5/6] Deploying agents + orchestrator (internal)..."
create_agent "$SYMPTOM_APP"    "healthlink-symptom:latest"    "$SYMPTOM_PORT"
create_agent "$DOCTOR_APP"     "healthlink-doctor:latest"     "$DOCTOR_PORT"
create_agent "$SCHEDULING_APP" "healthlink-scheduling:latest" "$SCHEDULING_PORT"
create_agent "$SUMMARY_APP"    "healthlink-summary:latest"    "$SUMMARY_PORT"

az containerapp create \
    --name "$ORCH_APP" --resource-group "$RESOURCE_GROUP" --environment "$ENV_NAME" \
    --image "$ACR_SERVER/healthlink-orchestrator:latest" \
    --registry-server "$ACR_SERVER" --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
    --target-port "$ORCH_PORT" --ingress internal \
    --min-replicas 0 --max-replicas 3 --cpu 0.5 --memory 1.0Gi \
    --env-vars \
        "SYMPTOM_AGENT_URL=http://$SYMPTOM_APP" \
        "DOCTOR_AGENT_URL=http://$DOCTOR_APP" \
        "SCHEDULING_AGENT_URL=http://$SCHEDULING_APP" \
        "SUMMARY_AGENT_URL=http://$SUMMARY_APP" \
    --only-show-errors >/dev/null

echo "==> [6/6] Deploying api-gateway + streamlit (external)..."
az containerapp create \
    --name "$API_APP" --resource-group "$RESOURCE_GROUP" --environment "$ENV_NAME" \
    --image "$ACR_SERVER/healthlink-api:latest" \
    --registry-server "$ACR_SERVER" --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
    --target-port "$API_PORT" --ingress external \
    --min-replicas 0 --max-replicas 5 --cpu 0.5 --memory 1.0Gi \
    --env-vars "ORCHESTRATOR_URL=http://$ORCH_APP" "DOCTOR_AGENT_URL=http://$DOCTOR_APP" "CORS_ORIGINS=*" \
    --only-show-errors >/dev/null

API_FQDN="$(az containerapp show --name "$API_APP" --resource-group "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv)"

az containerapp create \
    --name "$STREAMLIT_APP" --resource-group "$RESOURCE_GROUP" --environment "$ENV_NAME" \
    --image "$ACR_SERVER/healthlink-streamlit:latest" \
    --registry-server "$ACR_SERVER" --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
    --target-port "$STREAMLIT_PORT" --ingress external \
    --min-replicas 0 --max-replicas 3 --cpu 0.5 --memory 1.0Gi \
    --env-vars "API_BASE_URL=https://$API_FQDN/api/v1" \
    --only-show-errors >/dev/null

STREAMLIT_FQDN="$(az containerapp show --name "$STREAMLIT_APP" --resource-group "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn -o tsv)"

echo "==> Health check (gateway)..."
sleep 20
curl -fsS "https://$API_FQDN/api/v1/health" || echo "(not ready yet - containers may be cold-starting, retry in a minute)"

echo ""
echo "DONE."
echo "  Frontend (Streamlit): https://$STREAMLIT_FQDN"
echo "  API gateway:          https://$API_FQDN"
echo "  Swagger docs:         https://$API_FQDN/docs"
echo "Run ./teardown.sh when finished to stop all charges (ACR was $ACR_NAME)."
