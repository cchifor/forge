"""Scoped PR-gate enforcement for the mutmut workflow.

Companion to ``mutmut_enforce.py`` (which gates the nightly /
breaking-change-labelled lane on a survivors-max cap and is advisory).
This script gates the per-PR scoped lane on a kill-rate floor and is
blocking — a touched module dropping below its floor in
``tests/mutmut_baselines.json:pr_gate_modules`` fails the workflow.

Inputs:
    --baselines    Path to ``mutmut_baselines.json`` (defaults to
                   ``tests/mutmut_baselines.json`` relative to repo root).
    --results-dir  Directory of per-module kill-rate JSON files
                   produced by ``mutmut_kill_rate.py``. Each file is
                   named ``rate-<sanitised-path>.json`` where
                   ``<sanitised-path>`` is the module path with ``/``
                   replaced by ``_`` (matches the workflow's
                   ``${file//\\//_}`` artifact-naming convention).
    --touched      JSON list of repository-relative paths the PR
                   touched that are in the scoped subset. Only these
                   are enforced; modules absent from the touched set
                   are skipped (the scoped subset is small and a PR
                   that doesn't touch any scoped file should have
                   skipped this script entirely upstream).

Exit codes:
    0 — every touched scoped module meets its floor.
    1 — at least one touched module dropped below its floor; failure.
    2 — invalid arguments / missing baselines / no result data for a
        touched module (treated as failure to avoid silently green-
        lighting a PR when mutmut produced no output).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _sanitise(path: str) -> str:
    """Match the workflow's ``${file//\\//_}`` artifact-naming convention."""
    return path.replace("/", "_")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baselines", required=True, type=Path)
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument(
        "--touched",
        required=True,
        help="JSON list of touched scoped paths.",
    )
    args = parser.parse_args(argv)

    if not args.baselines.is_file():
        print(f"::error::baselines file missing: {args.baselines}", file=sys.stderr)
        return 2

    baselines = json.loads(args.baselines.read_text(encoding="utf-8"))
    pr_gate = baselines.get("pr_gate_modules") or {}
    if not pr_gate:
        print(
            "::error::tests/mutmut_baselines.json has no ``pr_gate_modules`` "
            "block; cannot enforce.",
            file=sys.stderr,
        )
        return 2

    try:
        touched: list[str] = json.loads(args.touched)
    except json.JSONDecodeError as exc:
        print(f"::error::--touched is not valid JSON: {exc}", file=sys.stderr)
        return 2

    if not touched:
        # The workflow's setup step gates this script behind a non-empty
        # touched list, but be defensive — a no-op success is correct
        # here (no scoped module touched -> nothing to enforce).
        print("no scoped modules touched — nothing to enforce (exit 0)")
        return 0

    # Patch-scoped enforcement: the shard mutates only the lines the PR
    # changed in each module, so the mutant count is tiny and per-PR-variable
    # — a whole-module kill-rate *floor* is meaningless against it. Instead
    # bound the number of SURVIVING changed-line mutants per module: every
    # mutant on new code should be killed (budget 0), with a documented
    # per-module allowance for diffs dominated by declarative/equivalent-mutant
    # code (e.g. lookup tables). A module with no changed lines yields 0
    # mutants and passes.
    budgets = baselines.get("pr_gate_changed_line_survivors_max") or {}

    failures: list[str] = []
    for module in touched:
        if module not in pr_gate:
            # The setup step only emits paths from pr_gate_modules, so
            # this would only fire on a misconfigured workflow. Treat
            # as a hard error so the mismatch is visible.
            print(
                f"::error::touched module {module!r} is not in "
                "pr_gate_modules; refusing to enforce a missing floor.",
                file=sys.stderr,
            )
            return 2

        budget = int(budgets.get(module, 0))
        rate_file = args.results_dir / f"rate-{_sanitise(module)}.json"
        if not rate_file.is_file():
            print(
                f"::error::no kill-rate JSON for touched module {module}: "
                f"expected {rate_file}. Mutmut may have crashed or the "
                "kill-rate extraction failed; this PR cannot be "
                "evaluated and is therefore blocked.",
                file=sys.stderr,
            )
            return 2

        summary = json.loads(rate_file.read_text(encoding="utf-8"))
        total = summary.get("total_evaluable", 0)
        survived = summary.get("survived", 0)
        timeout = summary.get("timeout", 0)

        if total == 0:
            # No changed lines (or no evaluable mutants) — nothing new to
            # guard. With patch scoping this is the common, legitimate case,
            # NOT a "no signal" failure.
            print(f"  [ok] {module}: 0 changed-line mutants — nothing to enforce")
            continue

        if timeout:
            # A timeout means the shard couldn't fully evaluate; don't let it
            # silently pass.
            print(
                f"::warning::{module}: {timeout} mutant(s) timed out — "
                "result may be incomplete."
            )

        if survived > budget:
            failures.append(
                f"{module}: {survived} surviving changed-line mutant(s) "
                f"> budget {budget} ({summary.get('killed', 0)} killed / "
                f"{survived} survived / {total} evaluable)"
            )
        else:
            print(
                f"  [ok] {module}: {survived} survived <= budget {budget} "
                f"({summary.get('killed', 0)}/{total} killed)"
            )

    if failures:
        print("::error::Mutmut PR-gate: changed lines have unkilled mutants:")
        for f in failures:
            print(f"  - {f}")
        print(
            "\nEither: (1) add tests that kill the new survivors (preferred — "
            "see the mutmut-pr-gate-* artifacts for which mutants survived), or "
            "(2) raise the module's budget in tests/mutmut_baselines.json's "
            "``pr_gate_changed_line_survivors_max`` block with a CHANGELOG entry "
            "justifying it (e.g. declarative/equivalent-mutant lines)."
        )
        return 1

    print("All touched scoped modules are within their changed-line survivor budget.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
