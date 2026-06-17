"""#258 — the nightly-failure issue body must name the failing scenario(s).

The notify job historically posted only a per-lane pass/fail table, so a
maintainer had to open the run and dig through logs to learn *which* scenario
broke. ``scripts/ci/nightly_failure_summary.py`` parses the per-scenario
``matrix-status-*`` JSON artifacts into a markdown section naming each failing
``scenario / lane`` with its error detail.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "ci"
    / "nightly_failure_summary.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("nightly_failure_summary", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(dir_: Path, name: str, rows: list[dict]) -> None:
    (dir_ / name).write_text(json.dumps(rows), encoding="utf-8")


class TestBuildSummary:
    def test_names_failing_scenario_and_detail(self, tmp_path: Path) -> None:
        mod = _load()
        _write(
            tmp_path,
            "stateless_py-update.json",
            [
                {
                    "scenario": "stateless_py",
                    "lane": "update",
                    "status": "fail",
                    "details": "database.none.engine Extra inputs are not permitted",
                    "missing_files": [],
                    "skipped_subchecks": [],
                }
            ],
        )
        _write(
            tmp_path,
            "py_vue_full.json",
            [
                {
                    "scenario": "py_vue_full",
                    "lane": "smoke",
                    "status": "ok",
                    "details": "",
                    "missing_files": [],
                    "skipped_subchecks": [],
                }
            ],
        )

        out = mod.build_summary(tmp_path)

        assert "stateless_py" in out
        assert "update" in out
        assert "database.none.engine" in out
        # Passing scenarios must not be listed.
        assert "py_vue_full" not in out

    def test_no_failures_emits_fallback(self, tmp_path: Path) -> None:
        mod = _load()
        _write(
            tmp_path,
            "ok.json",
            [{"scenario": "x", "lane": "smoke", "status": "ok", "details": ""}],
        )
        out = mod.build_summary(tmp_path)
        # No failing rows: a non-empty, honest fallback (not a misleading
        # "everything failed" or a crash).
        assert out.strip()
        assert "x / smoke" not in out

    def test_missing_dir_is_tolerated(self, tmp_path: Path) -> None:
        mod = _load()
        out = mod.build_summary(tmp_path / "does-not-exist")
        assert isinstance(out, str)
        assert out.strip()

    def test_malformed_json_is_skipped(self, tmp_path: Path) -> None:
        mod = _load()
        (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
        _write(
            tmp_path,
            "real.json",
            [
                {
                    "scenario": "node_svelte_min",
                    "lane": "roundtrip",
                    "status": "fail",
                    "details": "FR1 violation",
                }
            ],
        )
        out = mod.build_summary(tmp_path)
        assert "node_svelte_min" in out
        assert "roundtrip" in out
