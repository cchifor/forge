#!/usr/bin/env bash
#
# detect-prerelease.sh — PEP440-aware prerelease detection for release tags.
#
# Usage: detect-prerelease.sh <tag>
#   <tag> may carry a leading "v" (e.g. v1.2.0a1) or not (1.2.0a1).
#
# Emits "is_prerelease=true" or "is_prerelease=false" to stdout, and also
# appends the same line to $GITHUB_OUTPUT when that variable is set so the
# value can be consumed by `steps.<id>.outputs.is_prerelease` in a workflow.
#
# A version is a PRERELEASE when it carries any of:
#   * PEP440 pre-release segments:  a1 / b1 / rc1   (NO hyphen — the bug this
#                                                    fixes: contains('-') missed these)
#   * PEP440 dev-release segment:   .dev / .dev3
#   * legacy hyphenated suffixes:   -alpha / -beta / -rc / -anything
# A bare X.Y.Z (optionally "vX.Y.Z") is STABLE.
#
# Exit codes: 0 success; 2 missing arg; 3 unrecognisable version shape.
set -euo pipefail

emit() {
  echo "is_prerelease=$1"
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    echo "is_prerelease=$1" >>"$GITHUB_OUTPUT"
  fi
}

tag="${1:-}"
if [ -z "$tag" ]; then
  echo "usage: detect-prerelease.sh <tag>" >&2
  exit 2
fi

# Strip an optional leading "v".
version="${tag#v}"

# Must look like X.Y.Z (optionally with a suffix).
if ! [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
  echo "detect-prerelease.sh: '$tag' is not a valid version" >&2
  exit 3
fi

# Strip the X.Y.Z core; whatever remains is the suffix.
suffix="${version#[0-9]*.[0-9]*.[0-9]*}"
# The glob above is greedy-safe enough for the numeric core; recompute
# precisely with a regex capture for correctness.
if [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(.*)$ ]]; then
  suffix="${BASH_REMATCH[1]}"
fi

if [ -z "$suffix" ]; then
  emit false
  exit 0
fi

# PEP440 pre/dev (a1/b1/rc1/.devN, no hyphen) OR any legacy hyphen suffix.
if [[ "$suffix" =~ ^(a|b|rc)[0-9]+ ]] \
  || [[ "$suffix" =~ ^\.dev[0-9]* ]] \
  || [[ "$suffix" == -* ]]; then
  emit true
  exit 0
fi

# A trailing ".N" (post-release / 4-component) or "+build" metadata is not a
# prerelease.
emit false
exit 0
