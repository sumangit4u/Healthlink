# ============================================================================
# deploy.ps1 - ONE-SHOT deploy of the 7-service HealthLink stack to Azure
# Container Apps (Windows PowerShell). Primary deploy script on Windows.
#
#   streamlit / api-gateway  -> public   (--ingress external)
#   orchestrator + 4 agents  -> internal (--ingress internal)
#
# Everything goes in ONE resource group so teardown.ps1 deletes it all at once.
# GEMINI_API_KEY (or GEMINI_API_KEY_Orig) and PINECONE_API_KEY are read from the
# shared project .env and injected as Container App secrets.
#
# Prereqs: Azure CLI (`az`), a subscription, and `az login` already done.
# Usage:   ./deploy.ps1
$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot

# ---- Config ----
# min-replicas=1 keeps the internal chain warm so health probes never hit a
# cold-starting container (heavy langchain imports take several seconds). To
# minimise cost instead, set the --min-replicas below to 0 and accept a slow,
# occasionally "degraded"-looking first request after idle.
$ResourceGroup = "healthlink-rg"
$Location      = "centralindia"
$AcrName       = "healthlinkacr$(Get-Random -Maximum 99999)"
$EnvName       = "healthlink-env"
$EnvFile       = Join-Path $ScriptDir "..\..\Module 2 - RAG\.env"

$StreamlitApp = "healthlink-streamlit"; $StreamlitPort = 8501
$ApiApp       = "healthlink-api";        $ApiPort       = 8000
$OrchApp      = "healthlink-orchestrator"; $OrchPort    = 8001
$SymptomApp   = "healthlink-symptom";    $SymptomPort   = 8010
$DoctorApp    = "healthlink-doctor";     $DoctorPort    = 8011
$SchedulingApp= "healthlink-scheduling"; $SchedulingPort= 8012
$SummaryApp   = "healthlink-summary";    $SummaryPort   = 8013

# ---- Read model keys from the shared .env ----
if (-not (Test-Path $EnvFile)) { throw "Cannot find shared secrets file: $EnvFile" }
function Read-Key($name) {
    $line = Select-String -Path $EnvFile -Pattern "^\s*$name\s*=" | Select-Object -First 1
    if ($null -eq $line) { return "" }
    return ($line.Line -replace "^\s*$name\s*=", "").Trim().Trim('"').Trim("'")
}
$GeminiKey = Read-Key "GEMINI_API_KEY"
if ([string]::IsNullOrWhiteSpace($GeminiKey)) { $GeminiKey = Read-Key "GEMINI_API_KEY_Orig" }
$PineconeKey = Read-Key "PINECONE_API_KEY"
if ([string]::IsNullOrWhiteSpace($GeminiKey))   { throw "GEMINI_API_KEY (or _Orig) not found in $EnvFile" }
if ([string]::IsNullOrWhiteSpace($PineconeKey)) { throw "PINECONE_API_KEY not found in $EnvFile" }

Write-Host "==> Ensuring containerapp extension + providers..."
az extension add --name containerapp --upgrade --only-show-errors | Out-Null
az provider register --namespace Microsoft.App --wait --only-show-errors | Out-Null
az provider register --namespace Microsoft.OperationalInsights --wait --only-show-errors | Out-Null
az provider register --namespace Microsoft.ContainerRegistry --wait --only-show-errors | Out-Null

Write-Host "==> [1/6] Resource group ($ResourceGroup in $Location)..."
az group create --name $ResourceGroup --location $Location --only-show-errors | Out-Null

Write-Host "==> [2/6] Container Registry ($AcrName, Basic SKU)..."
az acr create --resource-group $ResourceGroup --name $AcrName --sku Basic --admin-enabled true --only-show-errors | Out-Null

function Build-Image($image, $dockerfile) {
    Write-Host "    building $image ($dockerfile) ..."
    az acr build --registry $AcrName --image $image --file $dockerfile $ScriptDir --only-show-errors
    if ($LASTEXITCODE -ne 0) {
        Write-Host "!! Cloud build failed for $image - falling back to local Docker build + push."
        if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "Docker not found. Start Docker Desktop and rerun." }
        az acr login --name $AcrName
        docker build --platform linux/amd64 -t "$AcrName.azurecr.io/$image" -f (Join-Path $ScriptDir $dockerfile) $ScriptDir
        docker push "$AcrName.azurecr.io/$image"
    }
}

Write-Host "==> [3/6] Building all 7 images in the cloud..."
Build-Image "healthlink-streamlit:latest"    "services/streamlit/Dockerfile"
Build-Image "healthlink-api:latest"          "services/api_gateway/Dockerfile"
Build-Image "healthlink-orchestrator:latest" "services/orchestrator/Dockerfile"
Build-Image "healthlink-symptom:latest"      "services/symptom_agent/Dockerfile"
Build-Image "healthlink-doctor:latest"       "services/doctor_agent/Dockerfile"
Build-Image "healthlink-scheduling:latest"   "services/scheduling_agent/Dockerfile"
Build-Image "healthlink-summary:latest"      "services/summary_agent/Dockerfile"

Write-Host "==> [4/6] Container Apps environment ($EnvName)..."
az containerapp env create --name $EnvName --resource-group $ResourceGroup --location $Location --only-show-errors | Out-Null

$AcrServer = "$AcrName.azurecr.io"
$AcrUser = az acr credential show --name $AcrName --query username -o tsv
$AcrPass = az acr credential show --name $AcrName --query "passwords[0].value" -o tsv

function New-Agent($app, $image, $port) {
    Write-Host "    deploying $app (internal)..."
    az containerapp create `
        --name $app --resource-group $ResourceGroup --environment $EnvName `
        --image "$AcrServer/$image" `
        --registry-server $AcrServer --registry-username $AcrUser --registry-password $AcrPass `
        --target-port $port --ingress internal `
        --min-replicas 1 --max-replicas 3 --cpu 0.5 --memory 1.0Gi `
        --secrets "gemini-api-key=$GeminiKey" "pinecone-api-key=$PineconeKey" `
        --env-vars "GEMINI_API_KEY=secretref:gemini-api-key" "PINECONE_API_KEY=secretref:pinecone-api-key" `
        --only-show-errors | Out-Null
}

Write-Host "==> [5/6] Deploying agents + orchestrator (internal)..."
New-Agent $SymptomApp    "healthlink-symptom:latest"    $SymptomPort
New-Agent $DoctorApp     "healthlink-doctor:latest"     $DoctorPort
New-Agent $SchedulingApp "healthlink-scheduling:latest" $SchedulingPort
New-Agent $SummaryApp    "healthlink-summary:latest"    $SummaryPort

az containerapp create `
    --name $OrchApp --resource-group $ResourceGroup --environment $EnvName `
    --image "$AcrServer/healthlink-orchestrator:latest" `
    --registry-server $AcrServer --registry-username $AcrUser --registry-password $AcrPass `
    --target-port $OrchPort --ingress internal `
    --min-replicas 1 --max-replicas 3 --cpu 0.5 --memory 1.0Gi `
    --env-vars "SYMPTOM_AGENT_URL=http://$SymptomApp" "DOCTOR_AGENT_URL=http://$DoctorApp" "SCHEDULING_AGENT_URL=http://$SchedulingApp" "SUMMARY_AGENT_URL=http://$SummaryApp" `
    --only-show-errors | Out-Null

Write-Host "==> [6/6] Deploying api-gateway + streamlit (external)..."
az containerapp create `
    --name $ApiApp --resource-group $ResourceGroup --environment $EnvName `
    --image "$AcrServer/healthlink-api:latest" `
    --registry-server $AcrServer --registry-username $AcrUser --registry-password $AcrPass `
    --target-port $ApiPort --ingress external `
    --min-replicas 1 --max-replicas 5 --cpu 0.5 --memory 1.0Gi `
    --env-vars "ORCHESTRATOR_URL=http://$OrchApp" "DOCTOR_AGENT_URL=http://$DoctorApp" "CORS_ORIGINS=*" `
    --only-show-errors | Out-Null

$ApiFqdn = az containerapp show --name $ApiApp --resource-group $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv

az containerapp create `
    --name $StreamlitApp --resource-group $ResourceGroup --environment $EnvName `
    --image "$AcrServer/healthlink-streamlit:latest" `
    --registry-server $AcrServer --registry-username $AcrUser --registry-password $AcrPass `
    --target-port $StreamlitPort --ingress external `
    --min-replicas 1 --max-replicas 3 --cpu 0.5 --memory 1.0Gi `
    --env-vars "API_BASE_URL=https://$ApiFqdn/api/v1" `
    --only-show-errors | Out-Null

$StreamlitFqdn = az containerapp show --name $StreamlitApp --resource-group $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv

Write-Host "==> Health check (gateway)..."
Start-Sleep -Seconds 20
try { Invoke-RestMethod "https://$ApiFqdn/api/v1/health" | Out-Null; Write-Host "Gateway healthy." }
catch { Write-Host "(not ready yet - containers may be cold-starting, retry in a minute)" }

Write-Host ""
Write-Host "DONE."
Write-Host "  Frontend (Streamlit): https://$StreamlitFqdn"
Write-Host "  API gateway:          https://$ApiFqdn"
Write-Host "  Swagger docs:         https://$ApiFqdn/docs"
Write-Host "Run ./teardown.ps1 when finished to stop all charges (ACR was $AcrName)."
