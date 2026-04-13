#!/usr/bin/env bash
set -euo pipefail

# Build only UI code generation (Riverpod, Freezed, GoRouter).
# Skips swagger_parser -- use generate_api.sh when the API changes.

cd "$(dirname "$0")/.."

echo "Running build_runner (UI only)..."
dart run build_runner build --delete-conflicting-outputs

echo "Done!"
