#!/usr/bin/env bash
# Run from the repository root after a locked dev sync. No release is published.
set -euo pipefail

artifact_dir="${1:-.artifacts/release-smoke}"
mkdir -p "$artifact_dir"
package_version="$(uv run --locked python -c 'import forge; print(forge.__version__)')"
bash .github/scripts/check-tag-version.sh "v$package_version"
bash .github/scripts/detect-prerelease.sh "v$package_version"
bash .github/scripts/extract-changelog.sh Unreleased CHANGELOG.md > "$artifact_dir/release-notes.md"
uv build --out-dir "$artifact_dir"
uvx --from cyclonedx-bom cyclonedx-py environment .venv/bin/python \
  --output-format json --output-file "$artifact_dir/forge-sbom.cdx.json"

uv run --locked python - "$artifact_dir" "$package_version" <<'PY'
import json
import sys
import tomllib
from pathlib import Path

artifacts = Path(sys.argv[1])
version = sys.argv[2]
assert len(list(artifacts.glob("*.whl"))) == 1, "Expected one release wheel"
assert len(list(artifacts.glob("*.tar.gz"))) == 1, "Expected one release sdist"
assert (artifacts / "release-notes.md").read_text().strip(), "Release notes are empty"
sbom = json.loads((artifacts / "forge-sbom.cdx.json").read_text())
components = sbom["components"]
versions = {component["name"]: component["version"] for component in components}
assert versions.get("forge-cli") == version, "SBOM must describe the Forge environment"
locked = tomllib.loads(Path("uv.lock").read_text())["package"]
for package in locked:
    if package["name"] in {"copier", "hypothesis", "ty"}:
        assert versions.get(package["name"]) == package["version"], package["name"]
print("Release wheel, sdist, notes, and locked-environment SBOM verified")
PY
