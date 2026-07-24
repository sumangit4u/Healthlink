#!/usr/bin/env bash
# teardown.sh - ONE-SHOT delete of EVERYTHING created by deploy.sh.
#
# deploy.sh puts all 7 Container Apps, the shared environment, the Log Analytics
# workspace, AND the Container Registry inside ONE resource group, so a single
# `az group delete` removes the whole lot and stops all billing.
#
# Usage:  ./teardown.sh
set -euo pipefail

RESOURCE_GROUP="healthlink-rg"

echo "Deleting resource group '$RESOURCE_GROUP' and ALL resources inside it..."
az group delete --name "$RESOURCE_GROUP" --yes --no-wait

echo "Delete started (background). Verify with: az group show --name $RESOURCE_GROUP"
echo "(It should eventually report 'ResourceGroupNotFound'.)"
