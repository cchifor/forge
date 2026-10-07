"""Reject AI co-author trailers in new commits; historical cleanup is separate."""

from __future__ import annotations

import argparse
import re
import subprocess


def violations(repository: str, revision: str) -> list[str]:
    text = subprocess.run(
        ["git", "log", "--format=%H%x00%B%x00", revision],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    parts = text.split("\0")
    result = []
    for index in range(0, len(parts) - 1, 2):
        sha, message = parts[index].strip(), parts[index + 1]
        if re.search(r"(?im)^co-authored-by:.*(?:\bClaude\b|noreply@anthropic\.com)", message):
            result.append(sha)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("revision", help="Revision range, typically BASE..HEAD")
    parser.add_argument("--repository", default=".")
    args = parser.parse_args()
    invalid = violations(args.repository, args.revision)
    if invalid:
        raise SystemExit("Claude co-author trailers in: " + ", ".join(invalid))
