"""Write the current coverage percentage into committed artifacts.

Run this after ``pytest --cov --cov-report=json:coverage.json`` has
produced ``coverage.json`` in the repo root. The script:

1. Reads the project-wide coverage percentage from ``coverage.json``.
2. Writes ``.forge-coverage.json`` — a small committed file the
   matrix dashboard / README badge can read.
3. Refreshes the ``<!-- COVERAGE-BADGE -->`` block at the top of
   ``docs/coverage-policy.md`` with the current number.

The coverage CI job in ``.github/workflows/ci.yml`` is expected to
invoke this script and commit any diff so a stale value cannot drift
past a PR.

Exits 0 on success, non-zero on malformed inputs (to fail the CI
job early).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COVERAGE_JSON = REPO_ROOT / "coverage.json"
BADGE_JSON = REPO_ROOT / ".forge-coverage.json"
POLICY_DOC = REPO_ROOT / "docs" / "coverage-policy.md"

# Sentinels identifying the auto-managed block inside
# ``docs/coverage-policy.md``. Everything between them is replaced on
# each run; anything outside is left untouched so humans can edit the
# rest of the doc freely.
BADGE_START = "<!-- COVERAGE-BADGE:START -->"
BADGE_END = "<!-- COVERAGE-BADGE:END -->"


def _read_coverage_percent(path: Path) -> float:
    """Return the project-wide covered percentage from ``coverage.json``.

    The pytest-cov json format records an aggregate ``totals`` object
    with ``percent_covered`` (a float 0-100). We round to one decimal
    for human display but keep the raw float in the badge JSON so
    downstream tooling can reason about deltas.
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} not found — run `pytest --cov --cov-report=json:coverage.json` first"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    totals = data.get("totals") or {}
    pct = totals.get("percent_covered")
    if not isinstance(pct, (int, float)):
        raise ValueError(
            f"{path} missing totals.percent_covered — unexpected coverage.json shape"
        )
    return float(pct)


def _write_badge_json(pct: float, path: Path) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {
        "percent_covered": pct,
        "display": f"{pct:.1f}%",
        "updated_at": now,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _refresh_policy_doc(pct: float, path: Path) -> None:
    """Rewrite the auto-managed block in ``coverage-policy.md``.

    If the block markers are missing, insert them right after the
    top-level header so the doc still picks up the next run. Humans
    editing the doc should leave the markers alone.
    """
    badge_block = (
        f"{BADGE_START}\n"
        f"**Project-wide coverage:** **{pct:.1f}%** "
        f"(auto-updated from `coverage.json` by `scripts/coverage_badge.py`)\n"
        f"{BADGE_END}\n"
    )

    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if BADGE_START in text and BADGE_END in text:
        # Keep non-greedy so multiple consecutive blocks (shouldn't happen,
        # but be defensive) collapse to one.
        pattern = re.compile(
            re.escape(BADGE_START) + r".*?" + re.escape(BADGE_END) + r"\n?",
            flags=re.DOTALL,
        )
        new_text = pattern.sub(badge_block, text, count=1)
    else:
        lines = text.splitlines(keepends=True) if text else ["# Coverage Policy\n", "\n"]
        # Insert after the first blank line following the H1, if any;
        # otherwise prepend.
        insert_at = 0
        for i, line in enumerate(lines):
            if line.strip() == "" and i > 0:
                insert_at = i + 1
                break
        prefix = "".join(lines[:insert_at])
        suffix = "".join(lines[insert_at:])
        new_text = prefix + badge_block + "\n" + suffix

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_text, encoding="utf-8")


def main() -> int:
    try:
        pct = _read_coverage_percent(COVERAGE_JSON)
    except (FileNotFoundError, ValueError) as e:
        print(f"coverage_badge: {e}", file=sys.stderr)
        return 2
    _write_badge_json(pct, BADGE_JSON)
    _refresh_policy_doc(pct, POLICY_DOC)
    print(f"coverage_badge: project-wide coverage = {pct:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
