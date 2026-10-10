#!/usr/bin/env bash
# Validates household.yaml and uploads it as the new version of the household-config
# secret, then destroys older versions so no stale personal data stays behind.
#
# Usage: GCLOUD_CONFIGURATION=<config> scripts/upload_household.sh <project-id> [file]
set -euo pipefail

: "${GCLOUD_CONFIGURATION:?set GCLOUD_CONFIGURATION to the gcloud configuration of the project owner}"
PROJECT_ID="${1:?project id}"
FILE="${2:-household.yaml}"
SECRET="household-config"

gc() { gcloud --configuration="$GCLOUD_CONFIGURATION" --project="$PROJECT_ID" "$@"; }

uv run --quiet python -c '
import sys
from pathlib import Path
from sekretariat.config import parse_household
members = parse_household(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(f"valid: {len(members)} member(s)")
' "$FILE"

NEW=$(gc secrets versions add "$SECRET" --data-file="$FILE" --format="value(name)")
echo "uploaded ${NEW##*/}"

for version in $(gc secrets versions list "$SECRET" --filter="state=ENABLED OR state=DISABLED" --format="value(name)"); do
  if [ "${version##*/}" != "${NEW##*/}" ]; then
    gc secrets versions destroy "${version##*/}" --secret="$SECRET" --quiet >/dev/null
    echo "destroyed old version ${version##*/}"
  fi
done
