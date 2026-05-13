"""Phase 4: concrete extractor behaviour for files / deps / env.

The Phase 3 ``tests/test_extractors.py`` covers framework wiring —
this file exercises the actual reverse-direction harvest:

* :class:`FileExtractor` — file-level three-way merge against the
  manifest's per-file baseline SHAs.
* :class:`DepsExtractor` — set diff between fragment-declared deps
  and the on-disk ``pyproject.toml`` / ``package.json`` / ``Cargo.toml``.
* :class:`EnvExtractor` — set diff between fragment-declared
  ``env_vars`` and the on-disk ``.env.example``.

The four scenarios per extractor (no-change / added / modified /
removed) cover the candidate-emission decision table. Edge cases
specific to each extractor live alongside the scenarios that
motivate them.

The :class:`InjectionExtractor` (kind = ``"block"``) is owned by a
parallel agent and isn't exercised here.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.config import BackendConfig, BackendLanguage
from forge.extractors import (
    CandidatePatch,
    DepsExtractor,
    EnvExtractor,
    ExtractionPlan,
    FileExtractor,
)
from forge.fragment_context import FragmentContext
from forge.fragments import Fragment, FragmentImplSpec
from forge.sync.merge import sha256_of_file

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mk_ctx(
    *,
    backend_dir: Path,
    project_root: Path,
    language: BackendLanguage = BackendLanguage.PYTHON,
    file_baselines: dict[str, str] | None = None,
) -> FragmentContext:
    return FragmentContext(
        backend_config=BackendConfig(
            name="api",
            project_name="P",
            language=language,
        ),
        backend_dir=backend_dir,
        project_root=project_root,
        options={},
        provenance=None,
        file_baselines=file_baselines or {},
    )


def _mk_plan(
    *,
    fragment_name: str = "frag-x",
    files: tuple[tuple[str, str], ...] = (),
    dependencies: tuple[str, ...] = (),
    env_vars: tuple[tuple[str, str], ...] = (),
) -> ExtractionPlan:
    return ExtractionPlan(
        fragment_name=fragment_name,
        files=files,
        injections=(),
        dependencies=dependencies,
        env_vars=env_vars,
    )


@pytest.fixture
def isolated_fragment_registry() -> Iterator[dict[str, Fragment]]:
    """Empty FRAGMENT_REGISTRY swap-in so tests don't see built-in fragments.

    The FileExtractor looks up ``plan.fragment_name`` against the
    real :data:`forge.fragments.FRAGMENT_REGISTRY` to find the on-
    disk ``files/`` tree. Tests need to register their own synthetic
    fragments without colliding with the built-in registry.
    """
    fragments: dict[str, Fragment] = {}
    with (
        patch("forge.fragments.FRAGMENT_REGISTRY", fragments),
        patch("forge.extractors.files.FRAGMENT_REGISTRY", fragments),
    ):
        yield fragments


def _make_fragment_files_dir(
    tmp_path: Path,
    fragment_name: str,
    *,
    files: dict[str, str | bytes],
) -> Path:
    """Materialise a synthetic fragment ``files/`` tree under tmp_path.

    Returns the absolute fragment_dir; the ``files/`` subtree lives
    under it. Used by the FileExtractor tests to build a fragment
    package that ``_resolve_fragment_dir`` can find via an absolute
    path (the registry's impl carries an absolute fragment_dir, so
    no built-in resolution path is needed).
    """
    fragment_dir = tmp_path / "fragments" / fragment_name
    files_dir = fragment_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    for relpath, content in files.items():
        target = files_dir / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
    return fragment_dir


def _register_synthetic_fragment(
    registry: dict[str, Fragment],
    *,
    name: str,
    fragment_dir: Path,
    language: BackendLanguage = BackendLanguage.PYTHON,
) -> None:
    """Inject a synthetic Fragment into the swapped-in registry."""
    registry[name] = Fragment(
        name=name,
        implementations={
            language: FragmentImplSpec(fragment_dir=str(fragment_dir)),
        },
    )


# ---------------------------------------------------------------------------
# FileExtractor
# ---------------------------------------------------------------------------


class TestFileExtractor:
    """File-level harvest. Bakes against the synthetic fragment tree."""

    def _bake(
        self,
        tmp_path: Path,
        registry: dict[str, Fragment],
        *,
        fragment_files: dict[str, str | bytes],
        project_files: dict[str, str | bytes] | None = None,
        baselines: dict[str, str] | None = None,
        plan_files: tuple[tuple[str, str], ...],
    ) -> tuple[FragmentContext, ExtractionPlan]:
        fragment_dir = _make_fragment_files_dir(tmp_path, "frag-x", files=fragment_files)
        _register_synthetic_fragment(registry, name="frag-x", fragment_dir=fragment_dir)

        project_root = tmp_path / "project"
        backend_dir = project_root  # one-directory layout for simplicity
        backend_dir.mkdir(parents=True, exist_ok=True)
        for relpath, content in (project_files or {}).items():
            target = backend_dir / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                target.write_bytes(content)
            else:
                target.write_text(content, encoding="utf-8")

        ctx = _mk_ctx(
            backend_dir=backend_dir,
            project_root=project_root,
            file_baselines=baselines or {},
        )
        plan = _mk_plan(fragment_name="frag-x", files=plan_files)
        return ctx, plan

    def test_empty_plan_returns_empty(self, tmp_path: Path) -> None:
        ctx = _mk_ctx(backend_dir=tmp_path, project_root=tmp_path)
        assert FileExtractor().extract(ctx, _mk_plan()) == []

    def test_no_change_emits_nothing(
        self,
        tmp_path: Path,
        isolated_fragment_registry: dict[str, Fragment],
    ) -> None:
        # Project file matches both baseline and upstream — converged.
        body = "alpha\nbeta\n"
        ctx, plan = self._bake(
            tmp_path,
            isolated_fragment_registry,
            fragment_files={"app/main.py": body},
            project_files={"app/main.py": body},
            baselines={"app/main.py": _sha_for(body)},
            plan_files=(("app/main.py", "app/main.py"),),
        )
        assert FileExtractor().extract(ctx, plan) == []

    def test_user_edit_emits_safe_apply(
        self,
        tmp_path: Path,
        isolated_fragment_registry: dict[str, Fragment],
    ) -> None:
        # User edited the file; upstream still matches baseline.
        upstream = "alpha\nbeta\n"
        edited = "alpha\nbeta\ngamma\n"
        ctx, plan = self._bake(
            tmp_path,
            isolated_fragment_registry,
            fragment_files={"app/main.py": upstream},
            project_files={"app/main.py": edited},
            baselines={"app/main.py": _sha_for(upstream)},
            plan_files=(("app/main.py", "app/main.py"),),
        )
        candidates = FileExtractor().extract(ctx, plan)
        assert len(candidates) == 1
        patch = candidates[0]
        assert patch.kind == "files"
        assert patch.risk == "safe-apply"
        assert patch.fragment == "frag-x"
        assert patch.backend == "api"
        assert patch.rel_path == "app/main.py"
        assert "+gamma" in patch.diff
        # Upstream is the "from" side of the unified diff.
        assert "--- a/app/main.py" in patch.diff
        assert "+++ b/app/main.py" in patch.diff

    def test_both_diverged_emits_conflict(
        self,
        tmp_path: Path,
        isolated_fragment_registry: dict[str, Fragment],
    ) -> None:
        # Baseline shipped one body; both upstream and project moved.
        baseline_body = "alpha\nbeta\n"
        upstream_body = "alpha\nbeta\nupstream-line\n"
        project_body = "alpha\nbeta\nproject-line\n"
        ctx, plan = self._bake(
            tmp_path,
            isolated_fragment_registry,
            fragment_files={"app/main.py": upstream_body},
            project_files={"app/main.py": project_body},
            baselines={"app/main.py": _sha_for(baseline_body)},
            plan_files=(("app/main.py", "app/main.py"),),
        )
        candidates = FileExtractor().extract(ctx, plan)
        assert len(candidates) == 1
        assert candidates[0].risk == "conflict"
        assert "-upstream-line" in candidates[0].diff
        assert "+project-line" in candidates[0].diff

    def test_no_baseline_emits_nothing(
        self,
        tmp_path: Path,
        isolated_fragment_registry: dict[str, Fragment],
    ) -> None:
        # No baseline recorded → pre-1.1 file. The reverse decide
        # returns "no-baseline"; the extractor surfaces nothing.
        ctx, plan = self._bake(
            tmp_path,
            isolated_fragment_registry,
            fragment_files={"app/main.py": "alpha\n"},
            project_files={"app/main.py": "user edited\n"},
            baselines={},  # no baseline
            plan_files=(("app/main.py", "app/main.py"),),
        )
        assert FileExtractor().extract(ctx, plan) == []

    def test_upstream_only_moved_emits_nothing(
        self,
        tmp_path: Path,
        isolated_fragment_registry: dict[str, Fragment],
    ) -> None:
        # Fragment shipped a bump but the user didn't edit — nothing
        # to harvest (forward update would apply, reverse skips).
        baseline_body = "alpha\n"
        upstream_body = "alpha\nupstream-bump\n"
        ctx, plan = self._bake(
            tmp_path,
            isolated_fragment_registry,
            fragment_files={"app/main.py": upstream_body},
            project_files={"app/main.py": baseline_body},
            baselines={"app/main.py": _sha_for(baseline_body)},
            plan_files=(("app/main.py", "app/main.py"),),
        )
        assert FileExtractor().extract(ctx, plan) == []

    def test_user_deleted_emits_safe_apply(
        self,
        tmp_path: Path,
        isolated_fragment_registry: dict[str, Fragment],
    ) -> None:
        # User deleted a fragment-tracked file. The decide function
        # surfaces this as ``safe-apply`` (with the caller deciding
        # whether to tag for review) — we follow that contract.
        upstream_body = "alpha\nbeta\n"
        ctx, plan = self._bake(
            tmp_path,
            isolated_fragment_registry,
            fragment_files={"app/main.py": upstream_body},
            project_files={},  # not on disk
            baselines={"app/main.py": _sha_for(upstream_body)},
            plan_files=(("app/main.py", "app/main.py"),),
        )
        candidates = FileExtractor().extract(ctx, plan)
        assert len(candidates) == 1
        assert candidates[0].risk == "safe-apply"
        # Empty current → diff removes everything that was upstream.
        assert "-alpha" in candidates[0].diff

    def test_binary_file_emits_needs_review_with_placeholder(
        self,
        tmp_path: Path,
        isolated_fragment_registry: dict[str, Fragment],
    ) -> None:
        # Both files contain null bytes — classic binary signature.
        # The decide function still classifies as "safe-apply" (user
        # edited, upstream didn't), but the extractor flips that to
        # "needs-review" because no meaningful unified diff exists.
        upstream_bytes = b"\x00\x01\x02upstream\n"
        edited_bytes = b"\x00\x01\x02edited\n"
        ctx, plan = self._bake(
            tmp_path,
            isolated_fragment_registry,
            fragment_files={"app/data.bin": upstream_bytes},
            project_files={"app/data.bin": edited_bytes},
            baselines={"app/data.bin": _sha_for_bytes(upstream_bytes)},
            plan_files=(("app/data.bin", "app/data.bin"),),
        )
        candidates = FileExtractor().extract(ctx, plan)
        assert len(candidates) == 1
        assert candidates[0].risk == "needs-review"
        assert candidates[0].diff == "<binary file changed>"

    def test_unregistered_fragment_returns_empty(
        self,
        tmp_path: Path,
        isolated_fragment_registry: dict[str, Fragment],
    ) -> None:
        # Plan references a fragment name with no registry entry.
        # The extractor cannot find the fragment_dir; emit nothing.
        ctx = _mk_ctx(backend_dir=tmp_path, project_root=tmp_path)
        plan = _mk_plan(
            fragment_name="unknown-frag",
            files=(("app/main.py", "app/main.py"),),
        )
        assert FileExtractor().extract(ctx, plan) == []


# ---------------------------------------------------------------------------
# DepsExtractor
# ---------------------------------------------------------------------------


class TestDepsExtractor:
    """Dependency-manifest drift harvest, Python / Node / Rust."""

    def _ctx(self, tmp_path: Path, language: BackendLanguage) -> FragmentContext:
        return _mk_ctx(
            backend_dir=tmp_path,
            project_root=tmp_path,
            language=language,
        )

    # -- Python ------------------------------------------------------------

    def _write_pyproject(self, backend_dir: Path, deps: list[str]) -> None:
        body = f'[project]\nname = "p"\nversion = "0.1.0"\ndependencies = {json.dumps(deps)}\n'
        (backend_dir / "pyproject.toml").write_text(body, encoding="utf-8")

    def test_empty_plan_returns_empty(self, tmp_path: Path) -> None:
        self._write_pyproject(tmp_path, ["fastapi>=0.110"])
        ctx = self._ctx(tmp_path, BackendLanguage.PYTHON)
        assert DepsExtractor().extract(ctx, _mk_plan()) == []

    def test_python_no_change(self, tmp_path: Path) -> None:
        deps = ("fastapi>=0.110", "pydantic>=2.0")
        self._write_pyproject(tmp_path, list(deps))
        ctx = self._ctx(tmp_path, BackendLanguage.PYTHON)
        plan = _mk_plan(dependencies=deps)
        assert DepsExtractor().extract(ctx, plan) == []

    def test_python_added_dep(self, tmp_path: Path) -> None:
        # Fragment declares slowapi; project also added redis.
        self._write_pyproject(tmp_path, ["slowapi>=0.1.9", "redis>=5.0"])
        ctx = self._ctx(tmp_path, BackendLanguage.PYTHON)
        plan = _mk_plan(dependencies=("slowapi>=0.1.9",))
        candidates = DepsExtractor().extract(ctx, plan)
        assert len(candidates) == 1
        c = candidates[0]
        assert c.kind == "deps"
        assert c.risk == "needs-review"
        assert c.rel_path == "pyproject.toml"
        payload = json.loads(c.diff)
        assert payload["action"] == "added"
        assert payload["name"] == "redis"
        assert payload["fragment_spec"] is None
        assert payload["project_spec"] == "redis>=5.0"

    def test_python_removed_dep(self, tmp_path: Path) -> None:
        # Fragment declares slowapi + fastapi; project only carries
        # fastapi → slowapi was removed. The other-direction (project
        # adding deps the fragment didn't declare) is covered by
        # test_python_added_dep — here we want a pure "removed" scenario,
        # so the project keeps every fragment-declared dep except one.
        self._write_pyproject(tmp_path, ["fastapi>=0.110"])
        ctx = self._ctx(tmp_path, BackendLanguage.PYTHON)
        plan = _mk_plan(dependencies=("slowapi>=0.1.9", "fastapi>=0.110"))
        candidates = DepsExtractor().extract(ctx, plan)
        assert len(candidates) == 1
        payload = json.loads(candidates[0].diff)
        assert payload["action"] == "removed"
        assert payload["name"] == "slowapi"
        assert payload["fragment_spec"] == "slowapi>=0.1.9"
        assert payload["project_spec"] is None

    def test_python_modified_dep_version_drift(self, tmp_path: Path) -> None:
        # Same dep, different version pin.
        self._write_pyproject(tmp_path, ["slowapi==0.1.11"])
        ctx = self._ctx(tmp_path, BackendLanguage.PYTHON)
        plan = _mk_plan(dependencies=("slowapi>=0.1.9",))
        candidates = DepsExtractor().extract(ctx, plan)
        assert len(candidates) == 1
        payload = json.loads(candidates[0].diff)
        assert payload["action"] == "modified"
        assert payload["name"] == "slowapi"
        assert payload["fragment_spec"] == "slowapi>=0.1.9"
        assert payload["project_spec"] == "slowapi==0.1.11"

    def test_python_missing_manifest_skips_gracefully(self, tmp_path: Path) -> None:
        # No pyproject.toml at all.
        ctx = self._ctx(tmp_path, BackendLanguage.PYTHON)
        plan = _mk_plan(dependencies=("slowapi>=0.1.9",))
        assert DepsExtractor().extract(ctx, plan) == []

    def test_python_empty_dependencies_plan_returns_empty(self, tmp_path: Path) -> None:
        self._write_pyproject(tmp_path, ["fastapi>=0.110"])
        ctx = self._ctx(tmp_path, BackendLanguage.PYTHON)
        # Plan has no fragment-declared deps — skip entirely.
        assert DepsExtractor().extract(ctx, _mk_plan()) == []

    # -- Node --------------------------------------------------------------

    def _write_package_json(self, backend_dir: Path, deps: dict[str, str]) -> None:
        body = json.dumps(
            {"name": "p", "version": "0.1.0", "dependencies": deps},
            indent=2,
        )
        (backend_dir / "package.json").write_text(body + "\n", encoding="utf-8")

    def test_node_added_dep(self, tmp_path: Path) -> None:
        self._write_package_json(
            tmp_path,
            {"fastify": "^4.20", "user-added": "1.0.0"},
        )
        ctx = self._ctx(tmp_path, BackendLanguage.NODE)
        plan = _mk_plan(dependencies=("fastify@^4.20",))
        candidates = DepsExtractor().extract(ctx, plan)
        assert len(candidates) == 1
        payload = json.loads(candidates[0].diff)
        assert payload["action"] == "added"
        assert payload["name"] == "user-added"

    def test_node_modified_dep(self, tmp_path: Path) -> None:
        self._write_package_json(tmp_path, {"fastify": "^4.30"})
        ctx = self._ctx(tmp_path, BackendLanguage.NODE)
        plan = _mk_plan(dependencies=("fastify@^4.20",))
        candidates = DepsExtractor().extract(ctx, plan)
        assert len(candidates) == 1
        payload = json.loads(candidates[0].diff)
        assert payload["action"] == "modified"
        assert payload["name"] == "fastify"
        assert payload["fragment_spec"] == "^4.20"
        assert payload["project_spec"] == "^4.30"

    # -- Rust --------------------------------------------------------------

    def _write_cargo_toml(self, backend_dir: Path, deps_body: str) -> None:
        body = f'[package]\nname = "p"\nversion = "0.1.0"\n\n[dependencies]\n{deps_body}'
        (backend_dir / "Cargo.toml").write_text(body, encoding="utf-8")

    def test_rust_added_dep(self, tmp_path: Path) -> None:
        self._write_cargo_toml(tmp_path, 'tower = "0.5"\nuser-added = "1.0"\n')
        ctx = self._ctx(tmp_path, BackendLanguage.RUST)
        plan = _mk_plan(dependencies=("tower@0.5",))
        candidates = DepsExtractor().extract(ctx, plan)
        assert len(candidates) == 1
        payload = json.loads(candidates[0].diff)
        assert payload["action"] == "added"
        assert payload["name"] == "user-added"

    def test_rust_modified_dep(self, tmp_path: Path) -> None:
        self._write_cargo_toml(tmp_path, 'tower = "0.6"\n')
        ctx = self._ctx(tmp_path, BackendLanguage.RUST)
        plan = _mk_plan(dependencies=("tower@0.5",))
        candidates = DepsExtractor().extract(ctx, plan)
        assert len(candidates) == 1
        payload = json.loads(candidates[0].diff)
        assert payload["action"] == "modified"
        assert payload["fragment_spec"] == "0.5"
        assert payload["project_spec"] == "0.6"


# ---------------------------------------------------------------------------
# EnvExtractor
# ---------------------------------------------------------------------------


class TestEnvExtractor:
    """``.env.example`` drift harvest."""

    def _ctx(self, tmp_path: Path) -> FragmentContext:
        return _mk_ctx(backend_dir=tmp_path, project_root=tmp_path)

    def _write_env(self, backend_dir: Path, lines: list[str]) -> None:
        (backend_dir / ".env.example").write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )

    def test_empty_plan_returns_empty(self, tmp_path: Path) -> None:
        self._write_env(tmp_path, ["FOO=bar"])
        ctx = self._ctx(tmp_path)
        assert EnvExtractor().extract(ctx, _mk_plan()) == []

    def test_no_change(self, tmp_path: Path) -> None:
        self._write_env(tmp_path, ["FOO=bar", "BAZ=qux"])
        ctx = self._ctx(tmp_path)
        plan = _mk_plan(env_vars=(("FOO", "bar"), ("BAZ", "qux")))
        assert EnvExtractor().extract(ctx, plan) == []

    def test_added_env_var(self, tmp_path: Path) -> None:
        # Fragment declares FOO; project also has USER_ADDED.
        self._write_env(tmp_path, ["FOO=bar", "USER_ADDED=hello"])
        ctx = self._ctx(tmp_path)
        plan = _mk_plan(env_vars=(("FOO", "bar"),))
        candidates = EnvExtractor().extract(ctx, plan)
        assert len(candidates) == 1
        c = candidates[0]
        assert c.kind == "env"
        assert c.risk == "needs-review"
        assert c.rel_path == ".env.example"
        payload = json.loads(c.diff)
        assert payload["action"] == "added"
        assert payload["key"] == "USER_ADDED"
        assert payload["fragment_value"] is None
        assert payload["project_value"] == "hello"

    def test_removed_env_var(self, tmp_path: Path) -> None:
        # Fragment declares FOO; project no longer has it.
        self._write_env(tmp_path, ["OTHER=x"])
        ctx = self._ctx(tmp_path)
        plan = _mk_plan(env_vars=(("FOO", "bar"),))
        candidates = EnvExtractor().extract(ctx, plan)
        # OTHER is in project but not in fragment → 1 "added" candidate.
        # FOO is in fragment but not in project → 1 "removed" candidate.
        actions = sorted(json.loads(c.diff)["action"] for c in candidates)
        assert actions == ["added", "removed"]
        removed = next(c for c in candidates if json.loads(c.diff)["action"] == "removed")
        payload = json.loads(removed.diff)
        assert payload["key"] == "FOO"
        assert payload["fragment_value"] == "bar"
        assert payload["project_value"] is None

    def test_modified_env_var(self, tmp_path: Path) -> None:
        # Same key, different value.
        self._write_env(tmp_path, ["FOO=user-tuned"])
        ctx = self._ctx(tmp_path)
        plan = _mk_plan(env_vars=(("FOO", "bar"),))
        candidates = EnvExtractor().extract(ctx, plan)
        assert len(candidates) == 1
        payload = json.loads(candidates[0].diff)
        assert payload["action"] == "modified"
        assert payload["key"] == "FOO"
        assert payload["fragment_value"] == "bar"
        assert payload["project_value"] == "user-tuned"

    def test_missing_env_file_returns_empty(self, tmp_path: Path) -> None:
        # No .env.example on disk at all.
        ctx = self._ctx(tmp_path)
        plan = _mk_plan(env_vars=(("FOO", "bar"),))
        assert EnvExtractor().extract(ctx, plan) == []

    def test_comments_and_blanks_ignored(self, tmp_path: Path) -> None:
        # Comment + blank lines + lines without ``=`` are skipped.
        # Only KEY=value rows count.
        self._write_env(
            tmp_path,
            [
                "# this is a comment",
                "",
                "FOO=bar",
                "no equals here",
                "BAZ=qux",
            ],
        )
        ctx = self._ctx(tmp_path)
        plan = _mk_plan(env_vars=(("FOO", "bar"), ("BAZ", "qux")))
        assert EnvExtractor().extract(ctx, plan) == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha_for(text: str) -> str:
    """SHA-256 matching ``sha256_of_file`` for a text body."""
    import hashlib  # noqa: PLC0415

    normalized = text.replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _sha_for_bytes(data: bytes) -> str:
    """SHA-256 matching ``sha256_of_file`` for a binary body."""
    import hashlib  # noqa: PLC0415

    return hashlib.sha256(data).hexdigest()


# Sanity check that the helpers agree with the real hasher. If
# ``sha256_of_file`` changes its normalisation policy, these tests
# will surface that with a clear failure rather than mysterious
# "no candidates" cases.
def test_sha_helpers_match_sha256_of_file(tmp_path: Path) -> None:
    text = "alpha\nbeta\n"
    p = tmp_path / "f.txt"
    p.write_text(text, encoding="utf-8")
    assert sha256_of_file(p) == _sha_for(text)

    raw = b"\x00\x01\x02"
    p2 = tmp_path / "f.bin"
    p2.write_bytes(raw)
    assert sha256_of_file(p2) == _sha_for_bytes(raw)


def test_candidate_patch_carries_all_required_fields(tmp_path: Path) -> None:
    """Smoke test: the dataclass shape is what extractors emit."""
    p = CandidatePatch(
        fragment="frag",
        backend="api",
        kind="files",
        rel_path="x.py",
        target_path=str(tmp_path / "x.py"),
        diff="",
        baseline_sha=None,
        current_sha="abc",
        risk="needs-review",
    )
    assert p.fragment == "frag"
    assert p.rationale == ""
