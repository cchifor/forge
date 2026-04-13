#!/usr/bin/env bash
set -euo pipefail

# Generate the Dart API client from the committed OpenAPI spec
# using swagger_parser. Configuration lives in swagger_parser.yaml.
#
# Usage:
#   bash scripts/generate_api.sh          # generate from committed spec
#   bash scripts/generate_api.sh --fetch  # fetch latest spec first, then generate

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

if [[ "${1:-}" == "--fetch" ]]; then
  bash "$SCRIPT_DIR/fetch_openapi.sh"
fi

echo "Cleaning previous generated code..."
rm -rf lib/src/api/generated

echo "Running swagger_parser..."
dart run swagger_parser

echo "Running build_runner for generated code..."
dart run build_runner build --delete-conflicting-outputs

echo "Done! Generated client at lib/src/api/generated/"
