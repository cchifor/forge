"""Epic U baseline enforcement for the mutmut workflow.

Reads ``tests/mutmut_baselines.json`` plus the per-shard ``mutmut
results`` text files emitted by the workflow and fails when any
module's kill rate drops below its declared floor.

Invoked from ``.github/workflows/mutmut.yml`` after the parallel
``mutate`` shards have completed. Each shard mutates one file and
uploads its ``mutmut results`` text as an artifact; this script
downloads them into a single directory and aggregates.

Usage::

    python .github/workflows/scripts/mutmut_enforce.py <results-dir>

Exit codes:
    0 — every module meets its floor, OR no result files found (skip-silently).
    1 — one or more modules regressed; GH Actions fails the job.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINES = REPO_ROOT / "tests" / "mutmut_baselines.json"


def _read_results_dir(results_dir: Path) -> str:
    """Concatenate every ``*.txt`` under ``results_dir`` (recursive).

    Each shard uploads its own artifact, and ``actions/download-artifact``
    flattens them into per-shard subdirectories — recursive glob picks
    those up. Empty input produces ``""`` so the caller can short-circuit.
    """
    if not results_dir.is_dir():
        return ""
    chunks: list[str] = []
    for txt in sorted(results_dir.rglob("*.txt")):
        try:
            chunks.append(txt.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(chunks)


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
    if len(sys.argv) != 2:
        print(
            "usage: mutmut_enforce.py <results-dir>\n"
            "  <results-dir> is the directory the workflow downloaded "
            "the per-shard mutmut-results-*.txt artifacts into.",
            file=sys.stderr,
        )
        return 2

    if not BASELINES.is_file():
        print(f"::warning::baselines file missing: {BASELINES}")
        return 2

    baselines = json.loads(BASELINES.read_text(encoding="utf-8"))
    modules = baselines["modules"]

    results = _read_results_dir(Path(sys.argv[1]))
    if not results.strip():
        print("::warning::no mutmut result files found — skipping enforcement")
        return 0

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
