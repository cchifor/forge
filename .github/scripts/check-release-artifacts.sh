#!/usr/bin/env bash
# Run from the repository root after a locked dev sync. No release is published.
set -euo pipefail

smoke_dir="$(mktemp -d "${TMPDIR:-/tmp}/forge-release-smoke.XXXXXX")"
trap 'rm -r -- "$smoke_dir"' EXIT
artifact_dir="$smoke_dir/dist"
mkdir -p "$artifact_dir"
package_version="$(uv run --locked python -c 'import forge; print(forge.__version__)')"
bash .github/scripts/check-tag-version.sh "v$package_version"
bash .github/scripts/detect-prerelease.sh "v$package_version"
# Routine CI must also pass immediately after a release empties Unreleased.
# Exercise extraction with a fixture; release.yml still checks real notes.
cat > "$smoke_dir/CHANGELOG.md" <<'CHANGELOG'
# Changelog

## [Unreleased]

### Fixed
- Release preparation smoke fixture.
CHANGELOG
bash .github/scripts/extract-changelog.sh Unreleased "$smoke_dir/CHANGELOG.md" > "$artifact_dir/release-notes.md"
uv build --out-dir "$artifact_dir"
UV_PROJECT_ENVIRONMENT="$smoke_dir/runtime" \
  uv sync --locked --all-extras --no-dev --no-editable
uvx --from cyclonedx-bom cyclonedx-py environment "$smoke_dir/runtime/bin/python" \
  --output-format json --output-file "$artifact_dir/forge-sbom.cdx.json"

"$smoke_dir/runtime/bin/python" - "$artifact_dir" "$package_version" <<'PY'
import json
import re
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
versions = {
    re.sub(r"[-_.]+", "-", component["name"]).lower(): component["version"]
    for component in components
}
assert versions.get("forge-cli") == version, "SBOM must describe the Forge environment"
locked = tomllib.loads(Path("uv.lock").read_text())["package"]
for package in locked:
    if package["name"] in {"copier", "jinja2", "pydantic"}:
        assert versions.get(package["name"]) == package["version"], package["name"]
assert not {"hypothesis", "ty", "pytest", "pre-commit"} & versions.keys(), "SBOM includes dev tools"
print("Release wheel, sdist, notes, and locked runtime SBOM verified")
PY

# Optional evidence copy; assertions always use this run's fresh staging area.
if [[ $# -gt 0 ]]; then
  mkdir -p "$1"
  cp "$artifact_dir/"* "$1/"
fi
