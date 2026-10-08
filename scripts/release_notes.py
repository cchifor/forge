#!/usr/bin/env python3
"""Print the CHANGELOG.md section of one version, for release notes.

    python scripts/release_notes.py 1.4.0 > notes.md
"""

import re
import sys
from pathlib import Path

HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\]")


def section(changelog: str, version: str) -> str:
    lines = changelog.splitlines()
    start = end = None
    for i, line in enumerate(lines):
        m = HEADING.match(line)
        if not m:
            continue
        if start is None and re.match(version, m.group("version")):
            start = i + 1
        elif start is not None:
            end = i
            break
    if start is None or end is None:
        return ""
    return "\n".join(lines[start:end]).strip() + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    text = Path(__file__).resolve().parent.parent.joinpath("CHANGELOG.md").read_text()
    notes = section(text, argv[1])
    sys.stdout.write(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
