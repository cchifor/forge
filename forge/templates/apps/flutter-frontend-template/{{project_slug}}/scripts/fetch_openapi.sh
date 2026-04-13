#!/usr/bin/env bash
set -euo pipefail

# Fetch the latest OpenAPI spec from the running backend.
# The spec is committed to openapi/ so the project builds offline;
# run this script whenever the API changes.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SPEC_URL="${OPENAPI_SPEC_URL:-http://localhost:5000/openapi.json}"
SPEC_FILE="$PROJECT_DIR/openapi/openapi.json"

echo "Fetching OpenAPI spec from $SPEC_URL ..."
curl -sf "$SPEC_URL" -o "$SPEC_FILE"
echo "Saved to $SPEC_FILE"
