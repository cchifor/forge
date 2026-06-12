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
# Exits 1 (with a stderr message) when the section is absent or empty, so the
# release job fails loudly instead of cutting a GitHub Release with empty notes.
# Used by release.yml's github-release job (WS-4.2).
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

# String-prefix matching (no dynamic regex — version strings contain '.' and
# '[' which are regex-significant). A section opens with "## [<ver>]" or
# "## [<ver> " (space before a date / "targeting" suffix) and closes at the
# next "## [" heading.
body="$(
  awk -v ver="$version" '
    BEGIN {
      open_exact = "## [" ver "]"
      open_space = "## [" ver " "
    }
    /^## \[/ {
      if (in_section) { exit }
      if (index($0, open_exact) == 1 || index($0, open_space) == 1) {
        in_section = 1
        next
      }
      next
    }
    in_section { print }
  ' "$changelog"
)"

# Trim leading and trailing blank lines.
body="$(printf '%s\n' "$body" | awk '
  { lines[NR] = $0 }
  END {
    first = 0; last = 0
    for (i = 1; i <= NR; i++) {
      if (lines[i] ~ /[^[:space:]]/) { if (first == 0) first = i; last = i }
    }
    if (first == 0) exit
    for (i = first; i <= last; i++) print lines[i]
  }
')"

if [ -z "$(printf '%s' "$body" | tr -d '[:space:]')" ]; then
  echo "extract-changelog.sh: section [$version] not found or empty in $changelog" >&2
  exit 1
fi

printf '%s\n' "$body"
