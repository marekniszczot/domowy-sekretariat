#!/usr/bin/env bash
# Builds the image for Cloud Run (linux/amd64), pushes it to Artifact Registry and
# deploys it to the `web` service and the `jobs` job (same image, other command).
# Terraform owns everything else about both and ignores the image, so this does not
# fight `terraform apply`.
#
# Usage: GCLOUD_CONFIGURATION=<config> scripts/deploy.sh <project-id> [region]
set -euo pipefail

: "${GCLOUD_CONFIGURATION:?set GCLOUD_CONFIGURATION to the gcloud configuration of the project owner}"
PROJECT_ID="${1:?project id}"
REGION="${2:-europe-central2}"
REGISTRY="${REGION}-docker.pkg.dev"
IMAGE="${REGISTRY}/${PROJECT_ID}/app/web:$(git rev-parse --short HEAD)-$(date +%Y%m%d%H%M%S)"

cd "$(dirname "$0")/.."
if [ -n "$(git status --porcelain)" ]; then
  echo "warning: uncommitted changes are included in the image" >&2
fi

# A short-lived token, so the registry is never tied to the active gcloud account.
gcloud auth print-access-token --configuration="$GCLOUD_CONFIGURATION" |
  docker login -u oauth2accesstoken --password-stdin "https://${REGISTRY}" >/dev/null
docker buildx build --platform linux/amd64 -t "$IMAGE" --push .
gcloud run services update web --image="$IMAGE" --region="$REGION" \
  --configuration="$GCLOUD_CONFIGURATION" --project="$PROJECT_ID"
gcloud run jobs update jobs --image="$IMAGE" --region="$REGION" \
  --configuration="$GCLOUD_CONFIGURATION" --project="$PROJECT_ID"
