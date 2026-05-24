"""Read ``.mutmut-cache`` and emit per-module kill-rate JSON.

Companion to ``mutmut_pr_gate.py``. The ``mutmut results`` command in
mutmut 2.5.0 hits a pony-ORM bytecode-decompiler crash on Python 3.13
(``IndexError: tuple index out of range`` in ``pony.orm.decompiling``);
the CI runs on Python 3.13 so we read the SQLite cache directly
instead of parsing the text output.

The cache schema (mutmut 2.x) stores one row per mutant in the
``Mutant`` table with a ``status`` column:

    ok_killed       — tests caught the mutant
    bad_survived    — tests passed; the mutant escaped
    bad_timeout     — test runner took too long
    ok_suspicious   — slow but didn't time out
    untested        — mutmut crashed / was interrupted before this one

Kill rate is reported as ``killed / (killed + survived)`` — timeouts
and suspicious are flaky-test signals, not "mutant escaped" signals.
``untested`` is excluded entirely (an interrupted run shouldn't be
counted as evidence).

Usage::

    python mutmut_kill_rate.py <cache-path> > rate.json

Output schema::

    {
      "killed": int,
      "survived": int,
      "timeout": int,
      "suspicious": int,
      "untested": int,
      "total_evaluable": int,   # killed + survived
      "kill_rate": float | null  # null when total_evaluable == 0
    }
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_STATUS_KEYS = {
    "ok_killed": "killed",
    "bad_survived": "survived",
    "bad_timeout": "timeout",
    "ok_suspicious": "suspicious",
    "untested": "untested",
}


def summarise(cache_path: Path) -> dict:
    counts = {v: 0 for v in _STATUS_KEYS.values()}
    if not cache_path.exists():
        return _finalise(counts)
    with sqlite3.connect(str(cache_path)) as conn:
        for status, count in conn.execute("SELECT status, COUNT(*) FROM Mutant GROUP BY status"):
            key = _STATUS_KEYS.get(status)
            if key is not None:
                counts[key] += count
            # Unknown status keys are ignored — mutmut sometimes adds
            # transient states (e.g. "skipped") that don't belong in
            # either numerator or denominator.
    return _finalise(counts)


def _finalise(counts: dict) -> dict:
    total_evaluable = counts["killed"] + counts["survived"]
    kill_rate = counts["killed"] / total_evaluable if total_evaluable > 0 else None
    return {
        **counts,
        "total_evaluable": total_evaluable,
        "kill_rate": kill_rate,
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print(
            "usage: mutmut_kill_rate.py <.mutmut-cache path>",
            file=sys.stderr,
        )
        return 2
    summary = summarise(Path(argv[0]))
    json.dump(summary, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
