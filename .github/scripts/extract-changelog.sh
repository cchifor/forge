#!/usr/bin/env bash
#
# extract-changelog.sh — print one CHANGELOG section's body.
#
# Usage: extract-changelog.sh <version-or-Unreleased> <changelog-path>
#
# Matches a heading of the form:
#   ## [Unreleased]
#   ## [1.2.0]
#   ## [1.2.0] - 2026-05-31
#   ## [1.2.0] — targeting 1.3
# and prints every line until the next "## [" heading, with leading/trailing
# blank lines trimmed.
#
# Exits 1 (with a stderr message) when the section is absent or empty, so a
# release job fails loudly instead of publishing empty notes. Both release.yml
# and release-dryrun.yml share this single extractor (WS-4.2).
set -euo pipefail

version="${1:-}"
changelog="${2:-}"

if [ -z "$version" ] || [ -z "$changelog" ]; then
  echo "usage: extract-changelog.sh <version|Unreleased> <changelog-path>" >&2
  exit 2
fi
if [ ! -f "$changelog" ]; then
  echo "extract-changelog.sh: no such file: $changelog" >&2
  exit 2
fi

body="$(
  awk -v ver="$version" '
    BEGIN { in_section = 0; found = 0 }
    # A new "## [" heading ends the current section.
    /^## \[/ {
      if (in_section) { exit }
      # Does this heading open the requested section? Match "## [<ver>]"
      # or "## [<ver> " (date / "targeting" suffixes after a space).
      hdr = $0
      if (hdr ~ ("^## \\[" ver "\\]") || hdr ~ ("^## \\[" ver "[][ ]")) {
        in_section = 1
        found = 1
        next
      }
      next
    }
    in_section { print }
  ' "$changelog"
)"

# Trim leading/trailing blank lines.
body="$(printf '%s\n' "$body" | sed -e '/./,$!d' | sed -e ':a' -e '/^\s*$/{$d;N;ba}')"

if [ -z "$(printf '%s' "$body" | tr -d '[:space:]')" ]; then
  echo "extract-changelog.sh: section [$version] not found or empty in $changelog" >&2
  exit 1
fi

printf '%s\n' "$body"
