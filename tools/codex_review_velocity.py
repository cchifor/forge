#!/usr/bin/env python3
"""Measure codex-review velocity: rounds per merged PR over a rolling window.

The forge codex-review velocity policy (see the architectural improvement
plan and ``docs/MAINTAINER_ONBOARDING.md``) gates PRs touching critical
modules on a single codex round, with a second round only if the first
leaves PUSHBACK markers. Two rounds is the hard cap. If the median round
count per merged PR rises above 2, the policy itself needs revisiting:
either the gating list is too broad, the codex prompt isn't crisp, or
reviewers are not converging fast enough.

This script counts ``codex: review round N`` commits on each PR's branch
and reports per-PR statistics for a rolling window (default 30 days).

Usage::

    python tools/codex_review_velocity.py
    python tools/codex_review_velocity.py --since 90
    python tools/codex_review_velocity.py --json
    python tools/codex_review_velocity.py --strict   # exit 1 if median > 2

The script is dependency-free (stdlib + ``git``). It is safe to run from
CI on every merge to ``main``, from a maintainer's terminal, or from
the ``forge`` directory after ``git fetch origin main``.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
from pathlib import Path

_CODEX_PREFIX = "codex: review round"
_MERGE_PATTERN = re.compile(r"^Merge pull request #(\d+)")


def _run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"git failed ({' '.join(args)}):\n{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout


def _merged_prs(repo: Path, since_days: int, branch: str) -> list[tuple[int, str]]:
    """Return ``(pr_number, merge_sha)`` for each merged PR in the window."""
    log = _run_git(
        [
            "log",
            "--merges",
            f"--since={since_days} days ago",
            branch,
            "--format=%H%x09%s",
        ],
        cwd=repo,
    )
    out: list[tuple[int, str]] = []
    for line in log.splitlines():
        if not line.strip():
            continue
        sha, subject = line.split("\t", 1)
        match = _MERGE_PATTERN.match(subject)
        if match:
            out.append((int(match.group(1)), sha))
    return out


def _round_count_for_pr(repo: Path, merge_sha: str) -> int:
    """Count ``codex: review round N`` commits on this PR's branch."""
    parents = (
        _run_git(
            ["log", "--format=%P", "-n", "1", merge_sha],
            cwd=repo,
        )
        .strip()
        .split()
    )
    if len(parents) < 2:
        return 0
    base, head = parents[0], parents[1]
    commits = _run_git(
        ["log", f"{base}..{head}", "--format=%s"],
        cwd=repo,
    )
    return sum(1 for line in commits.splitlines() if line.startswith(_CODEX_PREFIX))


def _summarize(rounds_per_pr: list[tuple[int, int]], window_days: int) -> dict[str, object]:
    counts = [c for _, c in rounds_per_pr]
    if not counts:
        return {
            "window_days": window_days,
            "pr_count": 0,
            "round_total": 0,
            "round_median": 0,
            "round_max": 0,
            "round_p95": 0,
            "prs_over_two_rounds": [],
        }
    return {
        "window_days": window_days,
        "pr_count": len(counts),
        "round_total": sum(counts),
        "round_median": statistics.median(counts),
        "round_max": max(counts),
        "round_p95": (statistics.quantiles(counts, n=20)[-1] if len(counts) >= 20 else max(counts)),
        "prs_over_two_rounds": sorted(pr for pr, c in rounds_per_pr if c > 2),
    }


def _format_text(summary: dict[str, object]) -> str:
    lines = [
        f"Codex review velocity — last {summary['window_days']} days",
        f"  Merged PRs:           {summary['pr_count']}",
        f"  Codex rounds total:   {summary['round_total']}",
        f"  Rounds/PR (median):   {summary['round_median']}",
        f"  Rounds/PR (max):      {summary['round_max']}",
        f"  Rounds/PR (p95):      {summary['round_p95']}",
    ]
    overruns = summary["prs_over_two_rounds"]
    if overruns:
        lines.append(f"  PRs above 2 rounds:   {overruns}")
    else:
        lines.append("  PRs above 2 rounds:   (none)")
    if summary["round_median"] and float(summary["round_median"]) > 2:
        lines.append("")
        lines.append("  WARN: median exceeds 2 — policy revision indicated.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure codex-review rounds per merged PR.",
    )
    parser.add_argument(
        "--since",
        type=int,
        default=30,
        help="Rolling window in days (default: 30).",
    )
    parser.add_argument(
        "--branch",
        type=str,
        default="main",
        help="Branch whose merge history to scan (default: main).",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Path to the git repo (default: current working directory).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with status 1 when median exceeds 2 rounds.",
    )
    args = parser.parse_args(argv)

    prs = _merged_prs(args.repo, args.since, args.branch)
    rounds_per_pr = [(pr_number, _round_count_for_pr(args.repo, sha)) for pr_number, sha in prs]
    summary = _summarize(rounds_per_pr, args.since)

    if args.json:
        print(json.dumps(summary, indent=2, default=float))
    else:
        print(_format_text(summary))

    if args.strict and summary["round_median"] and float(summary["round_median"]) > 2:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
