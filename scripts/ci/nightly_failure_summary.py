"""Render a markdown summary of failing matrix scenarios for the nightly issue.

The ``matrix-nightly`` workflow uploads one ``matrix-status-*`` artifact per
scenario+lane — each a JSON array of rows shaped like::

    [{"scenario": "stateless_py", "lane": "update", "status": "fail",
      "details": "database.none.engine ...", "missing_files": [...], ...}]

This reads every JSON file under a directory, keeps the rows whose ``status``
is ``"fail"``, and prints a markdown section naming each failing
``scenario / lane`` with its error detail — so the auto-filed
``nightly-failure`` issue says *what* broke, not just *which lane*.

Usage::

    python scripts/ci/nightly_failure_summary.py [STATUS_DIR]

``STATUS_DIR`` defaults to ``matrix-status-raw`` (the path the workflow
downloads the merged artifacts to). Always exits 0 and always prints a
non-empty section, so the workflow can splice the output unconditionally.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_DETAIL_MAX = 300


def _failing_rows(status_dir: Path) -> list[dict]:
    rows: list[dict] = []
    if not status_dir.is_dir():
        return rows
    for path in sorted(status_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A truncated / unreadable artifact must not sink the summary.
            continue
        if not isinstance(data, list):
            continue
        for row in data:
            if isinstance(row, dict) and row.get("status") == "fail":
                rows.append(row)
    return rows


def build_summary(status_dir: Path) -> str:
    """Return a markdown section naming the failing scenarios (always non-empty)."""
    rows = _failing_rows(status_dir)
    if not rows:
        return (
            "### Failing scenarios\n\n"
            "_No per-scenario status artifacts reported a failure — the failure "
            "is at the job/infra level (gate, setup, or dashboard). See the run "
            "logs._\n"
        )

    rows.sort(key=lambda r: (str(r.get("scenario", "")), str(r.get("lane", ""))))
    lines = ["### Failing scenarios", "", "| scenario | lane | detail |", "| --- | --- | --- |"]
    for row in rows:
        scenario = str(row.get("scenario", "?"))
        lane = str(row.get("lane", "?"))
        detail = " ".join(str(row.get("details") or "").split())
        if len(detail) > _DETAIL_MAX:
            detail = detail[:_DETAIL_MAX] + "…"
        # Escape pipes so the cell can't break the table.
        detail = detail.replace("|", "\\|") or "—"
        lines.append(f"| `{scenario}` | {lane} | {detail} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    status_dir = Path(argv[1]) if len(argv) > 1 else Path("matrix-status-raw")
    sys.stdout.write(build_summary(status_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
