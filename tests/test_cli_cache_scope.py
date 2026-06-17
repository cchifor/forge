"""#258 — the read-only sync verbs must install the per-invocation
``manifest_cache_scope`` like ``update`` / ``harvest`` already do.

Each verb's CLI entry point should wrap its underlying sync function in
``manifest_cache_scope()`` so repeated ``forge.toml`` reads (e.g. accept's
per-block-candidate baseline lookups) parse the manifest once. We assert
the property directly: the active cache ContextVar must be set when the
underlying function is invoked.
"""

from __future__ import annotations

import argparse
from typing import Any, Callable

import pytest

from forge.sync import _manifest_cache


class _Stop(Exception):
    """Sentinel raised by the stub once it has recorded the cache state."""


def _capture_scope(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    run: Callable[[argparse.Namespace], Any],
    ns: argparse.Namespace,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def stub(*_args: Any, **_kwargs: Any) -> Any:
        captured["active"] = _manifest_cache._active_cache.get()
        raise _Stop

    monkeypatch.setattr(target, stub)
    with pytest.raises(_Stop):
        run(ns)
    return captured


class TestReadOnlyVerbsInstallCacheScope:
    def test_verify_installs_cache_scope(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        from forge.cli.commands.verify import _run_verify

        ns = argparse.Namespace(project_path=str(tmp_path))
        cap = _capture_scope(
            monkeypatch, "forge.cli.commands.verify.verify_project", _run_verify, ns
        )
        assert cap["active"] is not None, "verify did not install manifest_cache_scope"

    def test_resolve_installs_cache_scope(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        from forge.cli.commands.resolve import _run_resolve

        ns = argparse.Namespace(project_path=str(tmp_path), quiet=True)
        cap = _capture_scope(
            monkeypatch,
            "forge.cli.commands.resolve.resolve_sidecars",
            _run_resolve,
            ns,
        )
        assert cap["active"] is not None, "resolve did not install manifest_cache_scope"

    def test_accept_installs_cache_scope(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        from forge.cli.commands.accept_harvested import _run_accept_harvested

        ns = argparse.Namespace(
            project_path=str(tmp_path),
            accept_harvested=str(tmp_path / "bundle.json"),
        )
        cap = _capture_scope(
            monkeypatch,
            "forge.cli.commands.accept_harvested.accept_harvested",
            _run_accept_harvested,
            ns,
        )
        assert cap["active"] is not None, "accept did not install manifest_cache_scope"

    def test_reapply_installs_cache_scope(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        from forge.cli.commands.reapply_baseline import _run_reapply_baseline

        ns = argparse.Namespace(project_path=str(tmp_path))
        cap = _capture_scope(
            monkeypatch,
            "forge.cli.commands.reapply_baseline.reapply_baseline",
            _run_reapply_baseline,
            ns,
        )
        assert cap["active"] is not None, "reapply did not install manifest_cache_scope"
