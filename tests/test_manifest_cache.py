"""Tests for the per-invocation forge.toml cache (Initiative #6).

Covers three guarantees:

* In-scope reads coalesce — N calls produce one underlying parse.
* Out-of-scope reads pass through to the real loader (no behaviour
  drift for legacy callers that don't open the cache scope).
* The scope is reset cleanly on exit — a second scope in the same
  process starts empty, and a mid-run write+re-read after the
  cache was repopulated picks up the new content.
* The merge-zone applier consumes the cache: every merge injection
  in a fragment triggers exactly one ``read_forge_toml`` call when
  the scope is active.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest

from forge.sync._manifest_cache import (
    _peek_cache_size,
    cached_read_forge_toml,
    manifest_cache_scope,
)
from forge.sync.manifest import read_forge_toml


def _write_manifest(path: Path, *, project_name: str = "demo") -> None:
    """Stamp a minimal v4 manifest the read path can parse cleanly."""
    path.write_text(
        dedent(
            f"""
            [forge]
            schema_version = 4
            version = "1.3.0"
            project_name = "{project_name}"

            [forge.templates]
            python = "services/python-service-template"

            [forge.options]

            [forge.option_origins]
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


class TestScopeBasics:
    def test_no_scope_means_passthrough(self, tmp_path: Path) -> None:
        # Outside a scope, cached_read_forge_toml must hit
        # read_forge_toml on every call (no caching) so legacy
        # callers see no change.
        manifest = tmp_path / "forge.toml"
        _write_manifest(manifest)

        with patch(
            "forge.sync.manifest.read_forge_toml",
            wraps=read_forge_toml,
        ) as spy:
            cached_read_forge_toml(manifest)
            cached_read_forge_toml(manifest)
            cached_read_forge_toml(manifest)

        assert spy.call_count == 3
        # No active scope → peek returns the sentinel.
        assert _peek_cache_size() == -1

    def test_in_scope_coalesces_repeated_reads(self, tmp_path: Path) -> None:
        manifest = tmp_path / "forge.toml"
        _write_manifest(manifest)

        with (
            manifest_cache_scope(),
            patch(
                "forge.sync.manifest.read_forge_toml",
                wraps=read_forge_toml,
            ) as spy,
        ):
            data_a = cached_read_forge_toml(manifest)
            data_b = cached_read_forge_toml(manifest)
            data_c = cached_read_forge_toml(manifest)

            # Three logical reads, one tomlkit parse.
            assert spy.call_count == 1
            # Identity-equal — the cache returns the same instance.
            assert data_a is data_b is data_c
            # The cache holds exactly one entry (one resolved path).
            assert _peek_cache_size() == 1

    def test_scope_resets_on_exit(self, tmp_path: Path) -> None:
        manifest = tmp_path / "forge.toml"
        _write_manifest(manifest)

        with manifest_cache_scope():
            cached_read_forge_toml(manifest)
            assert _peek_cache_size() == 1

        # Exit drops the scope entirely (sentinel back to -1).
        assert _peek_cache_size() == -1

        # A second invocation in the same process starts empty.
        with (
            manifest_cache_scope(),
            patch(
                "forge.sync.manifest.read_forge_toml",
                wraps=read_forge_toml,
            ) as spy,
        ):
            cached_read_forge_toml(manifest)
            assert spy.call_count == 1

    def test_relative_and_absolute_paths_collapse(self, tmp_path: Path) -> None:
        # The cache keys on Path.resolve() so two different surface
        # forms of the same on-disk file share one cache entry.
        manifest = tmp_path / "forge.toml"
        _write_manifest(manifest)

        with (
            manifest_cache_scope(),
            patch(
                "forge.sync.manifest.read_forge_toml",
                wraps=read_forge_toml,
            ) as spy,
        ):
            cached_read_forge_toml(manifest)
            cached_read_forge_toml(Path(str(manifest)))  # different Path instance
            # Symlinked alias resolves to the same target.
            alias = tmp_path / "alias.toml"
            alias.symlink_to(manifest)
            cached_read_forge_toml(alias)

            assert spy.call_count == 1
            assert _peek_cache_size() == 1

    def test_nested_scope_shadows_outer(self, tmp_path: Path) -> None:
        # The inner scope installs its own cache; the outer one is
        # restored on exit. Lifetimes nest cleanly.
        manifest = tmp_path / "forge.toml"
        _write_manifest(manifest)

        with manifest_cache_scope():
            cached_read_forge_toml(manifest)
            assert _peek_cache_size() == 1
            with manifest_cache_scope():
                # Inner scope starts empty.
                assert _peek_cache_size() == 0
                cached_read_forge_toml(manifest)
                assert _peek_cache_size() == 1
            # Outer cache survives the inner pop.
            assert _peek_cache_size() == 1

    def test_exceptions_not_cached(self, tmp_path: Path) -> None:
        # Missing-file exceptions must NOT be cached — the file may
        # appear mid-scope (the updater writes forge.toml at the end
        # of a run; some sub-flow might still race a read).
        manifest = tmp_path / "forge.toml"

        with manifest_cache_scope():
            with pytest.raises(FileNotFoundError):
                cached_read_forge_toml(manifest)
            # Cache still empty — the failed call didn't poison it.
            assert _peek_cache_size() == 0

            _write_manifest(manifest)
            # Subsequent read after the file appears must succeed.
            data = cached_read_forge_toml(manifest)
            assert data.project_name == "demo"

    def test_mid_scope_rewrite_invalidates(self, tmp_path: Path) -> None:
        # Defence in depth: the updater re-stamps forge.toml at the
        # END of _update_locked, after every applier has consumed
        # baselines. Today no in-scope read happens post-restamp, so
        # a path-only cache would be safe. But future call paths
        # might add such a read; pin the mtime-arm of the cache key
        # so an in-scope rewrite is automatically picked up on the
        # next call instead of returning stale data.
        import os
        import time

        manifest = tmp_path / "forge.toml"
        _write_manifest(manifest, project_name="original")

        with manifest_cache_scope():
            first = cached_read_forge_toml(manifest)
            assert first.project_name == "original"
            assert _peek_cache_size() == 1

            # Sleep + bump mtime explicitly so the rewrite is visible
            # on filesystems with coarse mtime resolution.
            time.sleep(0.01)
            _write_manifest(manifest, project_name="restamped")
            st = manifest.stat()
            os.utime(
                manifest,
                ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000),
            )

            second = cached_read_forge_toml(manifest)
            assert second.project_name == "restamped"
            # The cache should still hold a single entry — the new
            # mtime overwrites the old key:value pair.
            assert _peek_cache_size() == 1


class TestAppliesToMergeBaseline:
    """End-to-end: the merge-zone applier no longer re-parses forge.toml
    per merge block when the cache scope is active.

    Drives :func:`forge.appliers.injection._load_merge_baseline` once
    per simulated merge injection, then asserts the underlying
    :func:`read_forge_toml` was called exactly once.
    """

    def test_merge_baseline_lookups_share_one_parse(self, tmp_path: Path) -> None:
        from forge.appliers.injection import _load_merge_baseline  # noqa: PLC0415

        manifest = tmp_path / "forge.toml"
        # Carry a few merge_blocks so the lookup actually has data to
        # consume — proves the cached entry is the same object.
        manifest.write_text(
            dedent(
                """
                [forge]
                schema_version = 4
                version = "1.3.0"
                project_name = "demo"

                [forge.templates]
                python = "services/python-service-template"

                [forge.options]

                [forge.option_origins]

                [forge.merge_blocks."src/app/main.py::middleware_cors:REG"]
                sha256 = "deadbeef"

                [forge.merge_blocks."src/app/main.py::middleware_csp:REG"]
                sha256 = "cafef00d"

                [forge.merge_blocks."src/app/main.py::middleware_rate:REG"]
                sha256 = "12345678"
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        with (
            manifest_cache_scope(),
            patch(
                "forge.sync.manifest.read_forge_toml",
                wraps=read_forge_toml,
            ) as spy,
        ):
            # Simulate the pre-Init-6 hot path: each merge injection
            # called _load_merge_baseline once.
            a = _load_merge_baseline(tmp_path, "src/app/main.py::middleware_cors:REG")
            b = _load_merge_baseline(tmp_path, "src/app/main.py::middleware_csp:REG")
            c = _load_merge_baseline(tmp_path, "src/app/main.py::middleware_rate:REG")
            # Unknown key falls through (still a cache hit, not a re-parse).
            d = _load_merge_baseline(tmp_path, "src/app/main.py::unknown:REG")

        assert a == "deadbeef"
        assert b == "cafef00d"
        assert c == "12345678"
        assert d is None
        # 4 logical lookups, 1 underlying parse — the Init #6 win.
        assert spy.call_count == 1

    def test_merge_baseline_works_without_scope(self, tmp_path: Path) -> None:
        # Defensive: callers (e.g. direct unit tests) that invoke the
        # applier without an active cache scope must still get correct
        # results — they just don't get the perf win.
        from forge.appliers.injection import _load_merge_baseline  # noqa: PLC0415

        manifest = tmp_path / "forge.toml"
        manifest.write_text(
            dedent(
                """
                [forge]
                schema_version = 4
                version = "1.3.0"
                project_name = "demo"

                [forge.templates]
                python = "services/python-service-template"

                [forge.options]

                [forge.option_origins]

                [forge.merge_blocks."src/app/main.py::middleware_cors:REG"]
                sha256 = "deadbeef"
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        sha = _load_merge_baseline(tmp_path, "src/app/main.py::middleware_cors:REG")
        assert sha == "deadbeef"

    def test_missing_manifest_returns_none(self, tmp_path: Path) -> None:
        # No forge.toml on disk — the helper short-circuits before
        # touching the cache, mirroring the pre-Init-6 contract.
        from forge.appliers.injection import _load_merge_baseline  # noqa: PLC0415

        with manifest_cache_scope():
            assert _load_merge_baseline(tmp_path, "anything") is None
            # Cache stays empty.
            assert _peek_cache_size() == 0
