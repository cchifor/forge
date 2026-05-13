"""Pre-apply audit for ``FORGE:BEGIN`` / ``FORGE:END`` sentinel pairs.

Epic H (1.1.0-alpha.1). A hand-edit that breaks a BEGIN/END pair
(deleting one side, duplicating a tag, nesting two pairs) silently
corrupts re-injection: the injector finds the broken block, believes
it's a valid existing block, and produces duplicate or misplaced
output on re-apply.

This auditor scans every target file the update plan will touch and
reports structural problems before the injector runs, so the user
gets a clear pointer at the file + tag + line number rather than
mysterious output.

Issue kinds:
    - ``orphan-begin``: a ``FORGE:BEGIN <tag>`` with no matching END
      below it.
    - ``orphan-end``: a ``FORGE:END <tag>`` with no preceding BEGIN.
    - ``duplicate-begin``: the same tag opens twice in one file.
    - ``duplicate-end``: the same tag closes twice in one file.
    - ``nested-pair``: a second BEGIN for a different tag appears
      between an already-open BEGIN and its END.
    - ``end-before-begin``: an END appears before its matching BEGIN
      in the file.

The auditor does not modify files — it only reports. Fixing is the
user's job (follow-up Epic adds ``forge --repair-sentinels``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from forge.errors import (
    INJECTION_SENTINEL_CORRUPT,
    InjectionError,
)

SentinelIssueKind = Literal[
    "orphan-begin",
    "orphan-end",
    "duplicate-begin",
    "duplicate-end",
    "nested-pair",
    "end-before-begin",
]

_BEGIN_RE = re.compile(r"FORGE:BEGIN\s+(\S+)")
_END_RE = re.compile(r"FORGE:END\s+(\S+)")


@dataclass(frozen=True)
class SentinelIssue:
    """One structural problem found in one file."""

    file: Path
    kind: SentinelIssueKind
    tag: str
    line: int  # 1-indexed to match editor messages


def audit_file(file: Path) -> list[SentinelIssue]:
    """Scan ``file`` for sentinel-structure issues.

    Returns an empty list on a clean file. Non-existent files return
    an empty list — the injector will raise its own missing-target
    error later.
    """
    if not file.is_file():
        return []
    try:
        text = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # Binary file or permission error — not our problem to audit.
        return []

    lines = text.splitlines()
    issues: list[SentinelIssue] = []
    # Stack of (tag, line) for tracking open BEGINs.
    open_stack: list[tuple[str, int]] = []
    # Seen BEGIN tags in this file — for duplicate detection.
    seen_begins: set[str] = set()
    seen_ends: set[str] = set()

    for idx, line in enumerate(lines, start=1):
        begin = _BEGIN_RE.search(line)
        end = _END_RE.search(line)

        if begin:
            tag = begin.group(1)
            if tag in seen_begins:
                issues.append(SentinelIssue(file, "duplicate-begin", tag, idx))
            else:
                seen_begins.add(tag)
            if open_stack:
                # Already-open BEGIN → nested pair
                outer_tag, _ = open_stack[-1]
                if outer_tag != tag:
                    issues.append(SentinelIssue(file, "nested-pair", tag, idx))
            open_stack.append((tag, idx))

        if end:
            tag = end.group(1)
            if tag in seen_ends:
                issues.append(SentinelIssue(file, "duplicate-end", tag, idx))
            else:
                seen_ends.add(tag)
            # Is there an open BEGIN for this tag?
            match_idx = next((i for i, (t, _) in enumerate(open_stack) if t == tag), None)
            if match_idx is None:
                # END without a preceding BEGIN
                if tag not in seen_begins:
                    issues.append(SentinelIssue(file, "end-before-begin", tag, idx))
                else:
                    # BEGIN was earlier but already closed — duplicate END already flagged
                    pass
            else:
                # Pop matching open BEGIN (and any inner opens — those
                # orphans get flagged at the end).
                open_stack.pop(match_idx)

    # Any BEGINs still open at EOF are orphans.
    for tag, line in open_stack:
        issues.append(SentinelIssue(file, "orphan-begin", tag, line))

    return issues


def audit_targets(target_paths: Iterable[Path]) -> list[SentinelIssue]:
    """Audit every file in ``target_paths``, aggregating issues."""
    issues: list[SentinelIssue] = []
    for path in target_paths:
        issues.extend(audit_file(path))
    return issues


def raise_if_corrupt(issues: list[SentinelIssue]) -> None:
    """Raise :class:`InjectionError` when the audit found any issues."""
    if not issues:
        return
    lines = [f"  {i.file}:{i.line}  {i.kind:<20}  {i.tag}" for i in issues[:10]]
    more = f"\n  ... and {len(issues) - 10} more" if len(issues) > 10 else ""
    raise InjectionError(
        f"Sentinel audit found {len(issues)} issue(s) before re-applying "
        f"fragments. Fix the BEGIN/END pairs and re-run — a mis-structured "
        f"sentinel silently corrupts re-injection.\n" + "\n".join(lines) + more,
        code=INJECTION_SENTINEL_CORRUPT,
        context={
            "issues": [
                {
                    "file": str(i.file),
                    "kind": i.kind,
                    "tag": i.tag,
                    "line": i.line,
                }
                for i in issues
            ],
        },
    )
