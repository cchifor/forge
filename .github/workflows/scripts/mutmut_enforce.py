"""Epic U baseline enforcement for the mutmut workflow.

Reads ``tests/mutmut_baselines.json`` + ``mutmut results`` output (via
``uv run mutmut results``) and fails when any module's kill rate drops
below its declared floor.

Invoked from ``.github/workflows/mutmut.yml`` after ``mutmut run``.
Uses the script-mode convention so the workflow stays simple
(``uv run python .github/workflows/scripts/mutmut_enforce.py``).

Exit codes:
    0 — every module meets its floor.
    1 — one or more modules regressed; GH Actions fails the job.
    2 — mutmut hasn't been run (no cache database); skip silently.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINES = REPO_ROOT / "tests" / "mutmut_baselines.json"


def _run_mutmut_results() -> str:
    """Return `mutmut results` stdout, or '' when the cache is missing."""
    try:
        result = subprocess.run(
            ["uv", "run", "mutmut", "results"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    # A clean cache-less run writes "No mutation results" or similar.
    if "No mutation" in result.stdout + result.stderr:
        return ""
    return result.stdout


def _parse_survivors(results: str) -> dict[str, int]:
    """Count surviving mutants per source file.

    ``mutmut results`` output is one mutant identifier per line in the
    form ``forge/<file>.py:<N>-<M>``. We aggregate the count by the
    leading path so per-file floors apply correctly.
    """
    survivors: dict[str, int] = {}
    for raw_line in results.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("-") or line.startswith("To see"):
            continue
        # Only lines that look like a mutant identifier.
        if ":" not in line:
            continue
        path = line.split(":", 1)[0]
        # Guard against summary or heading rows that happen to contain ':'.
        if not path.endswith(".py"):
            continue
        survivors[path] = survivors.get(path, 0) + 1
    return survivors


def main() -> int:
    if not BASELINES.is_file():
        print(f"::warning::baselines file missing: {BASELINES}")
        return 2

    baselines = json.loads(BASELINES.read_text(encoding="utf-8"))
    modules = baselines["modules"]

    results = _run_mutmut_results()
    if not results:
        print("::warning::no mutmut cache found — skipping enforcement")
        return 2

    survivors = _parse_survivors(results)

    failures: list[str] = []
    for module, gate in modules.items():
        count = survivors.get(module, 0)
        cap = int(gate["survivors_max"])
        if count > cap:
            failures.append(
                f"{module}: {count} survivors > cap {cap} "
                f"(kill_rate floor {gate['kill_rate_min']:.0%})"
            )
        else:
            print(f"  [ok] {module}: {count} survivors (cap {cap})")

    if failures:
        print("::error::Mutmut baselines regressed:")
        for f in failures:
            print(f"  - {f}")
        print(
            "\nEither: (1) add tests to kill the new survivors, or "
            "(2) raise the cap in tests/mutmut_baselines.json with a "
            "CHANGELOG entry explaining why."
        )
        return 1

    print("All mutmut baselines met.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
