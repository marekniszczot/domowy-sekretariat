#!/usr/bin/env bash
# One-time bootstrap: the Terraform state bucket has to exist before `terraform init`.
# The project itself and its billing link are created by hand (see infra/README.md).
#
# Usage: GCLOUD_CONFIGURATION=<config> infra/bootstrap.sh <project-id> <region>
set -euo pipefail

: "${GCLOUD_CONFIGURATION:?set GCLOUD_CONFIGURATION to the gcloud configuration of the project owner}"
PROJECT_ID="${1:?project id}"
REGION="${2:?region}"
BUCKET="${PROJECT_ID}-tfstate"

gc() { gcloud --configuration="$GCLOUD_CONFIGURATION" --project="$PROJECT_ID" "$@"; }

# The provider uses this project as quota project, so these must be on before the first plan.
gc services enable cloudresourcemanager.googleapis.com serviceusage.googleapis.com

if gc storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1; then
  echo "gs://${BUCKET} already exists"
else
  gc storage buckets create "gs://${BUCKET}" \
    --location="$REGION" \
    --uniform-bucket-level-access \
    --public-access-prevention
fi
gc storage buckets update "gs://${BUCKET}" --versioning

echo "bucket = \"${BUCKET}\"" > "$(dirname "$0")/backend.hcl"
echo "Wrote infra/backend.hcl"
