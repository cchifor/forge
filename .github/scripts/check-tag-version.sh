#!/usr/bin/env bash
#
# check-tag-version.sh — assert a release tag matches the package version.
#
# Usage: check-tag-version.sh <tag>
#   <tag> may carry a leading "v" (e.g. v1.2.0rc1) or not (1.2.0rc1).
#
# Guards the failure mode the audit flagged: a stable tag would otherwise
# drive a publish of the 1.2.0a1-versioned package as `latest`, because the
# publish jobs read the version from package metadata, not the tag. This makes
# tag/metadata disagreement a hard CI failure before anything is published.
#
# The authoritative version is the Python distribution version
# (forge/__init__.py ``__version__``), since the CLI is the lockstep anchor.
#
# Exit codes: 0 match; 2 missing arg; 3 cannot read package version; 4 mismatch.
set -euo pipefail

if [[ $# -lt 1 || -z "${1:-}" ]]; then
  echo "error: missing tag argument" >&2
  echo "usage: check-tag-version.sh <tag>" >&2
  exit 2
fi

tag="${1#v}" # strip optional leading v

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
init_py="$here/../../forge/__init__.py"
if [[ ! -f "$init_py" ]]; then
  echo "error: cannot find forge/__init__.py at $init_py" >&2
  exit 3
fi

pkg_version="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$init_py" | head -n1)"
if [[ -z "$pkg_version" ]]; then
  echo "error: could not parse __version__ from $init_py" >&2
  exit 3
fi

if [[ "$tag" != "$pkg_version" ]]; then
  echo "error: tag '$tag' does not match package __version__ '$pkg_version'." >&2
  echo "Bump forge/__init__.py (and the packages) to match the tag, or tag the package version." >&2
  exit 4
fi

echo "ok: tag and package version agree ($pkg_version)"
