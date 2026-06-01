"""WS-3.2: --dry-run must be side-effect-free on the host.

The frontend Copier path runs the template's ``_tasks`` (npm install, vue-tsc,
eslint, git init/commit) on the host machine. In ``--dry-run`` mode forge
should preview generation without executing those tasks. Copier 9.x exposes
``skip_tasks`` + ``pretend`` for exactly this; forge must thread its own
``dry_run`` through the frontend phase into ``run_copy``.
"""

from __future__ import annotations

import inspect

from forge import generator


def test_run_copier_accepts_dry_run():
    sig = inspect.signature(generator._run_copier)
    assert "dry_run" in sig.parameters, (
        "_run_copier must accept dry_run so the frontend Copier phase can skip "
        "host-mutating _tasks under --dry-run"
    )


def test_generate_frontend_threads_dry_run():
    for fn_name in ("_generate_frontend", "_generate_frontend_phase"):
        sig = inspect.signature(getattr(generator, fn_name))
        assert "dry_run" in sig.parameters, (
            f"{fn_name} must accept dry_run to honor --dry-run on the frontend path"
        )


def test_run_copier_skips_tasks_in_dry_run(monkeypatch, tmp_path):
    """In dry_run, run_copy must be called with skip_tasks=True (no host _tasks)."""
    captured: dict[str, object] = {}

    def fake_run_copy(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(generator, "run_copy", fake_run_copy)
    # _write_copier_answers reads the template dir; stub it so we isolate run_copy.
    monkeypatch.setattr(generator, "_write_copier_answers", lambda *a, **k: None)

    template = tmp_path / "tmpl"
    template.mkdir()
    dst = tmp_path / "out"

    generator._run_copier(template, dst, {"x": 1}, quiet=True, dry_run=True)
    assert captured.get("skip_tasks") is True, "dry_run must set skip_tasks=True"

    captured.clear()
    generator._run_copier(template, dst, {"x": 1}, quiet=True, dry_run=False)
    assert captured.get("skip_tasks") is False, "non-dry-run must run tasks (skip_tasks=False)"
