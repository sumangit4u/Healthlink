# teardown.ps1 - ONE-SHOT delete of EVERYTHING created by deploy.ps1.
#
# All 7 Container Apps, the shared environment, the Log Analytics workspace, and
# the Container Registry live in ONE resource group, so a single group delete
# removes the whole lot and stops all billing.
#
# Usage:  ./teardown.ps1
$ErrorActionPreference = "Stop"
$ResourceGroup = "healthlink-rg"

Write-Host "Deleting resource group '$ResourceGroup' and ALL resources inside it..."
az group delete --name $ResourceGroup --yes --no-wait

Write-Host "Delete started (background). Verify with: az group show --name $ResourceGroup"
Write-Host "(It should eventually report 'ResourceGroupNotFound'.)"
