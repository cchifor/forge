#!/usr/bin/env python3
"""Print the CHANGELOG.md section of one version, for release notes.

    python scripts/release_notes.py 1.4.0 > notes.md

Exits 1 (with a message on stderr) when the version has no section, so release automation never
publishes empty notes.
"""

import re
import sys
from pathlib import Path

HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\]")


def section(changelog: str, version: str) -> str:
    """The body of the `## [version]` section (exact match), or "" when there is none."""
    lines = changelog.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = HEADING.match(line)
        if not m:
            continue
        if start is not None:
            return "\n".join(lines[start:i]).strip() + "\n"
        if m.group("version") == version:
            start = i + 1
    if start is None:
        return ""
    return "\n".join(lines[start:]).strip() + "\n"     # the last section runs to the end of the file


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    path = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
    notes = section(path.read_text(encoding="utf-8"), argv[1])
    if not notes.strip():
        print(f"version {argv[1]} not found in {path.name}", file=sys.stderr)
        return 1
    sys.stdout.write(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
