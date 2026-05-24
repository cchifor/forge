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

        floor = float(pr_gate[module])
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
        rate = summary.get("kill_rate")
        total = summary.get("total_evaluable", 0)
        if rate is None or total == 0:
            print(
                f"::warning::{module}: mutmut produced no killed/survived "
                "mutants (possibly all timeouts). Treating as a failure to "
                "avoid green-lighting a PR with no signal."
            )
            failures.append(f"{module}: 0 evaluable mutants (floor {floor:.2%})")
            continue

        if rate < floor:
            failures.append(
                f"{module}: kill rate {rate:.2%} < floor {floor:.2%} "
                f"({summary['killed']} killed / {summary['survived']} "
                f"survived / {total} evaluable)"
            )
        else:
            print(
                f"  [ok] {module}: kill rate {rate:.2%} >= floor "
                f"{floor:.2%} ({summary['killed']}/{total})"
            )

    if failures:
        print("::error::Mutmut PR-gate floors regressed:")
        for f in failures:
            print(f"  - {f}")
        print(
            "\nEither: (1) add tests to kill the new survivors, or "
            "(2) lower the floor in tests/mutmut_baselines.json's "
            "``pr_gate_modules`` block with a CHANGELOG entry "
            "justifying the regression."
        )
        return 1

    print("All touched scoped modules meet their PR-gate floors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
