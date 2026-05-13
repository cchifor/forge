"""Tests for ``forge --harvest`` (Phase 4, bidirectional sync).

Covers the reverse-direction extraction backbone end-to-end:

* :class:`forge.extractors.injection.InjectionExtractor` — block-level
  harvest of user-edited merge zones (safe-apply / needs-review /
  conflict paths).
* :func:`forge.sync.project_to_forge.harvester.harvest_project` —
  orchestrator that walks ``forge.toml``, builds plans, runs the
  pipeline, and packages :class:`HarvestBundle` records.
* :class:`HarvestBundle.write` — on-disk bundle layout (manifest.json +
  per-fragment patch directories + README.md).
* CLI dispatch: ``forge --harvest --harvest-out`` materialises a bundle
  directory; ``--harvest-out=-`` streams JSON to stdout; ``--harvest-scope``
  / ``--harvest-include`` filter the candidate set.

Each test scaffolds a minimal project tree inline rather than going
through ``generate()`` — the harvester only needs ``forge.toml``,
the on-disk file with sentinels, and a baseline SHA recorded in the
manifest.
"""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

from forge.cli.commands.harvest import _run_harvest
from forge.config import BackendConfig, BackendLanguage
from forge.extractors import CandidatePatch, ExtractionPlan, InjectionExtractor
from forge.fragment_context import FragmentContext
from forge.fragments import MARKER_PREFIX
from forge.sync.manifest import write_forge_toml
from forge.sync.merge import MergeBlockCollector, sha256_of_text
from forge.sync.project_to_forge.bundle import write_bundle
from forge.sync.project_to_forge.harvester import (
    HarvestBundle,
    harvest_project,
)

# ---------------------------------------------------------------------------
# Fixtures — small helpers to scaffold a forge-tracked project inline.
# ---------------------------------------------------------------------------


def _block_text(feature_key: str, marker_bare: str, body: str) -> str:
    """Render a sentinel-wrapped block matching the injector's emitter.

    Note: production sentinels carry a ``fp:<hex>`` fingerprint on the
    BEGIN line; the prefix-substring matchers tolerate the v1-shape
    pair (no fingerprint), which keeps the test fixture small.
    """
    return (
        f"# {MARKER_PREFIX}BEGIN {feature_key}:{marker_bare}\n"
        f"{body}"
        f"# {MARKER_PREFIX}END {feature_key}:{marker_bare}\n"
    )


@pytest.fixture
def project_with_block(tmp_path: Path) -> dict[str, Any]:
    """Scaffold a project root with one tracked merge_block.

    Returns a dict carrying the relevant paths + SHAs so the test can
    assert against them without re-reading the manifest.
    """
    return _scaffold_project(tmp_path)


def _scaffold_project(
    tmp_path: Path,
    *,
    body: str = "# block body line 1\n# block body line 2\n",
    backend_name: str = "api",
) -> dict[str, Any]:
    """Build a tmp_path with a forge.toml + one block-bearing file."""
    backend_dir = tmp_path / "services" / backend_name
    src = backend_dir / "src" / "app"
    src.mkdir(parents=True)
    main_py = src / "main.py"
    block_segment = _block_text("middleware_cors", "MIDDLEWARE_REGISTRATION", body)
    main_py.write_text(f"# top\n{block_segment}# bottom\n")

    # The block-rel path is *project-root-relative*, not backend-relative.
    rel_path_in_project = f"services/{backend_name}/src/app/main.py"
    block_key = MergeBlockCollector.key_for(
        rel_path_in_project, "middleware_cors", "MIDDLEWARE_REGISTRATION"
    )
    baseline_sha = sha256_of_text(body)
    merge_blocks = {
        block_key: {
            "sha256": baseline_sha,
            "fragment_name": "middleware_cors",
            "fragment_version": "1.0.0",
        }
    }
    # Minimal pyproject.toml so _infer_backends detects this as a
    # Python backend.
    (backend_dir / "pyproject.toml").write_text(
        "[project]\nname = \"api\"\nversion = \"0.0.0\"\n"
    )

    write_forge_toml(
        tmp_path / "forge.toml",
        version="1.2.0",
        project_name="demo",
        templates={"python": "services/python-service-template"},
        options={},
        merge_blocks=merge_blocks,
    )
    return {
        "backend_dir": backend_dir,
        "main_py": main_py,
        "block_key": block_key,
        "baseline_sha": baseline_sha,
        "block_body": body,
        "block_rel_path": rel_path_in_project,
    }


def _mk_ctx(
    tmp_path: Path,
    *,
    backend_name: str = "api",
    merge_block_baselines: dict | None = None,
) -> FragmentContext:
    """Build a FragmentContext for unit-testing the InjectionExtractor.

    Attaches ``merge_block_baselines`` as a side-channel so the
    extractor sees the manifest's baseline without us having to write
    a forge.toml in tests that only exercise the extractor.
    """
    backend_dir = tmp_path / "services" / backend_name
    ctx = FragmentContext(
        backend_config=BackendConfig(
            name=backend_name,
            project_name="demo",
            language=BackendLanguage.PYTHON,
        ),
        backend_dir=backend_dir,
        project_root=tmp_path,
        options={},
        provenance=None,
    )
    if merge_block_baselines is not None:
        object.__setattr__(ctx, "merge_block_baselines", merge_block_baselines)
    return ctx


# ---------------------------------------------------------------------------
# InjectionExtractor unit tests
# ---------------------------------------------------------------------------


class _Inj:
    """Duck-typed _Injection record for tests."""

    def __init__(
        self,
        *,
        feature_key: str,
        target: str,
        marker: str,
        snippet: str,
    ) -> None:
        self.feature_key = feature_key
        self.target = target
        self.marker = marker
        self.snippet = snippet


class TestInjectionExtractorEmptyPlan:
    def test_empty_plan_returns_no_candidates(self, tmp_path: Path) -> None:
        ctx = _mk_ctx(tmp_path)
        plan = ExtractionPlan(
            fragment_name="middleware_cors",
            files=(),
            injections=(),
            dependencies=(),
            env_vars=(),
        )
        assert InjectionExtractor().extract(ctx, plan) == []


class TestInjectionExtractorSafeApply:
    def test_user_edited_block_produces_safe_apply(self, tmp_path: Path) -> None:
        meta = _scaffold_project(tmp_path)
        # User edits the block body — sentinels stay intact.
        edited = "# block body line 1\n# user added a line\n# block body line 2\n"
        original = _block_text(
            "middleware_cors", "MIDDLEWARE_REGISTRATION", meta["block_body"]
        )
        new_block = _block_text("middleware_cors", "MIDDLEWARE_REGISTRATION", edited)
        text = meta["main_py"].read_text().replace(original, new_block)
        meta["main_py"].write_text(text)

        ctx = _mk_ctx(
            tmp_path,
            merge_block_baselines={
                meta["block_key"]: {
                    "sha256": meta["baseline_sha"],
                    "fragment_name": "middleware_cors",
                }
            },
        )
        # The "upstream" body is the same as the original baseline
        # (the fragment template hasn't moved). The extractor classifies
        # this as safe-apply.
        plan = ExtractionPlan(
            fragment_name="middleware_cors",
            files=(),
            injections=(
                _Inj(
                    feature_key="middleware_cors",
                    target="src/app/main.py",
                    marker="FORGE:MIDDLEWARE_REGISTRATION",
                    snippet=meta["block_body"],
                ),
            ),
            dependencies=(),
            env_vars=(),
        )
        patches = InjectionExtractor().extract(ctx, plan)
        assert len(patches) == 1
        patch = patches[0]
        assert patch.kind == "block"
        assert patch.risk == "safe-apply"
        assert patch.fragment == "middleware_cors"
        assert patch.backend == "api"
        # Diff is upstream → current, so it should show the user's
        # additions as ``+`` lines.
        assert "+# user added a line" in patch.diff


class TestInjectionExtractorJinjaInterpolation:
    def test_user_edit_against_jinja_template_is_needs_review(
        self,
        tmp_path: Path,
    ) -> None:
        # Set up a block whose upstream snippet has a Jinja interpolation.
        # The user has edited the *rendered* body on disk. The extractor
        # should downgrade safe-apply → needs-review because back-porting
        # the literal edit into a templated snippet would corrupt the
        # template at re-render time.
        rendered_baseline = "rate_limit = 100\n"
        meta = _scaffold_project(tmp_path, body=rendered_baseline)
        edited_body = "rate_limit = 200\n"
        new_block = _block_text(
            "middleware_cors", "MIDDLEWARE_REGISTRATION", edited_body
        )
        original_block = _block_text(
            "middleware_cors", "MIDDLEWARE_REGISTRATION", rendered_baseline
        )
        meta["main_py"].write_text(
            meta["main_py"].read_text().replace(original_block, new_block)
        )

        ctx = _mk_ctx(
            tmp_path,
            merge_block_baselines={
                meta["block_key"]: {
                    "sha256": meta["baseline_sha"],
                    "fragment_name": "middleware_cors",
                }
            },
        )
        # Upstream snippet is the raw Jinja template — what the
        # extractor inspects for safety.
        plan = ExtractionPlan(
            fragment_name="middleware_cors",
            files=(),
            injections=(
                _Inj(
                    feature_key="middleware_cors",
                    target="src/app/main.py",
                    marker="FORGE:MIDDLEWARE_REGISTRATION",
                    snippet="rate_limit = {{ rate_limit }}\n",
                ),
            ),
            dependencies=(),
            env_vars=(),
        )
        patches = InjectionExtractor().extract(ctx, plan)
        # The extractor re-renders the snippet against the project
        # options; with no rate_limit in scope, render fails and we
        # land on needs-review (render_failed branch). When render
        # succeeds the Jinja-pattern check downgrades anyway.
        assert len(patches) == 1
        assert patches[0].risk == "needs-review"
        assert "Jinja" in patches[0].rationale or "render" in patches[0].rationale.lower()


class TestInjectionExtractorDeletedBlock:
    def test_missing_sentinels_produces_conflict(self, tmp_path: Path) -> None:
        meta = _scaffold_project(tmp_path)
        # User wiped the sentinel block entirely — neither BEGIN nor
        # END remain. The extractor can't anchor, so emits a conflict.
        meta["main_py"].write_text("# top\n# user replaced everything\n# bottom\n")

        ctx = _mk_ctx(
            tmp_path,
            merge_block_baselines={
                meta["block_key"]: {
                    "sha256": meta["baseline_sha"],
                    "fragment_name": "middleware_cors",
                }
            },
        )
        plan = ExtractionPlan(
            fragment_name="middleware_cors",
            files=(),
            injections=(
                _Inj(
                    feature_key="middleware_cors",
                    target="src/app/main.py",
                    marker="FORGE:MIDDLEWARE_REGISTRATION",
                    snippet=meta["block_body"],
                ),
            ),
            dependencies=(),
            env_vars=(),
        )
        patches = InjectionExtractor().extract(ctx, plan)
        assert len(patches) == 1
        assert patches[0].risk == "conflict"
        assert "sentinel" in patches[0].rationale.lower()


class TestInjectionExtractorIdempotent:
    def test_unedited_block_produces_no_candidate(self, tmp_path: Path) -> None:
        meta = _scaffold_project(tmp_path)
        # No user edits; on-disk body matches the manifest baseline AND
        # the upstream snippet. The extractor should not emit a candidate.
        ctx = _mk_ctx(
            tmp_path,
            merge_block_baselines={
                meta["block_key"]: {
                    "sha256": meta["baseline_sha"],
                    "fragment_name": "middleware_cors",
                }
            },
        )
        plan = ExtractionPlan(
            fragment_name="middleware_cors",
            files=(),
            injections=(
                _Inj(
                    feature_key="middleware_cors",
                    target="src/app/main.py",
                    marker="FORGE:MIDDLEWARE_REGISTRATION",
                    snippet=meta["block_body"],
                ),
            ),
            dependencies=(),
            env_vars=(),
        )
        patches = InjectionExtractor().extract(ctx, plan)
        assert patches == []


class TestInjectionExtractorNoBaseline:
    def test_no_baseline_in_manifest_produces_no_candidate(
        self,
        tmp_path: Path,
    ) -> None:
        # Manifest has no merge_block entry for this key (v1 project,
        # or the entry was hand-removed). The extractor should skip.
        meta = _scaffold_project(tmp_path)
        ctx = _mk_ctx(tmp_path, merge_block_baselines={})  # empty baselines
        plan = ExtractionPlan(
            fragment_name="middleware_cors",
            files=(),
            injections=(
                _Inj(
                    feature_key="middleware_cors",
                    target="src/app/main.py",
                    marker="FORGE:MIDDLEWARE_REGISTRATION",
                    snippet=meta["block_body"],
                ),
            ),
            dependencies=(),
            env_vars=(),
        )
        patches = InjectionExtractor().extract(ctx, plan)
        assert patches == []


# ---------------------------------------------------------------------------
# harvest_project orchestrator tests
# ---------------------------------------------------------------------------


class TestHarvestProjectEmpty:
    def test_clean_project_returns_empty_bundle(self, tmp_path: Path) -> None:
        # Scaffold a project with one tracked block, no user edits.
        _scaffold_project(tmp_path)
        bundle = harvest_project(tmp_path, quiet=True)
        assert isinstance(bundle, HarvestBundle)
        assert bundle.candidates == []
        # Bundle id has the expected shape.
        assert bundle.bundle_id.startswith("harvest-")

    def test_missing_forge_toml_raises(self, tmp_path: Path) -> None:
        # No forge.toml at all — harvester surfaces ProvenanceError.
        from forge.errors import PROVENANCE_MANIFEST_MISSING, ProvenanceError

        with pytest.raises(ProvenanceError) as exc:
            harvest_project(tmp_path, quiet=True)
        assert exc.value.code == PROVENANCE_MANIFEST_MISSING


class TestHarvestProjectUserEdit:
    def test_user_edit_surfaces_candidate(self, tmp_path: Path) -> None:
        # User edits an injection-block body in a manifest-tracked
        # project. The orchestrator should surface at least one
        # block-kind candidate. When the fragment isn't reachable from
        # the registry — which is the case here, ``middleware_cors``
        # exists in production but our test fixture doesn't register
        # it — the candidate lands as ``needs-review`` because we
        # cannot safely compare against the upstream Jinja template.
        # Either ``safe-apply`` (fragment reachable) or
        # ``needs-review`` (fragment unreachable) is acceptable for
        # the backbone contract.
        meta = _scaffold_project(tmp_path)
        edited = "# block body line 1\n# user added a line\n# block body line 2\n"
        new_block = _block_text("middleware_cors", "MIDDLEWARE_REGISTRATION", edited)
        original_block = _block_text(
            "middleware_cors", "MIDDLEWARE_REGISTRATION", meta["block_body"]
        )
        meta["main_py"].write_text(
            meta["main_py"].read_text().replace(original_block, new_block)
        )

        bundle = harvest_project(tmp_path, quiet=True)
        block_candidates = [c for c in bundle.candidates if c.kind == "block"]
        assert len(block_candidates) == 1
        cand = block_candidates[0]
        assert cand.risk in ("safe-apply", "needs-review")
        assert cand.fragment == "middleware_cors"
        # The current_sha reflects the post-edit body, distinct from
        # the manifest baseline. baseline_sha should be present.
        assert cand.baseline_sha == meta["baseline_sha"]
        assert cand.current_sha != cand.baseline_sha


class TestHarvestProjectScopeFilter:
    def test_scope_excludes_unlisted_fragments(self, tmp_path: Path) -> None:
        meta = _scaffold_project(tmp_path)
        # User edit
        edited = meta["block_body"] + "# new\n"
        new_block = _block_text("middleware_cors", "MIDDLEWARE_REGISTRATION", edited)
        original_block = _block_text(
            "middleware_cors", "MIDDLEWARE_REGISTRATION", meta["block_body"]
        )
        meta["main_py"].write_text(
            meta["main_py"].read_text().replace(original_block, new_block)
        )
        # Scope to a different fragment name — no candidates.
        bundle = harvest_project(tmp_path, scope=("some_other_fragment",), quiet=True)
        assert bundle.candidates == []

    def test_scope_includes_listed_fragment(self, tmp_path: Path) -> None:
        meta = _scaffold_project(tmp_path)
        edited = meta["block_body"] + "# new\n"
        new_block = _block_text("middleware_cors", "MIDDLEWARE_REGISTRATION", edited)
        original_block = _block_text(
            "middleware_cors", "MIDDLEWARE_REGISTRATION", meta["block_body"]
        )
        meta["main_py"].write_text(
            meta["main_py"].read_text().replace(original_block, new_block)
        )
        bundle = harvest_project(tmp_path, scope=("middleware_cors",), quiet=True)
        block_candidates = [c for c in bundle.candidates if c.kind == "block"]
        assert len(block_candidates) == 1


class TestHarvestProjectIncludeFilter:
    def test_include_blocks_only_skips_other_extractors(
        self,
        tmp_path: Path,
    ) -> None:
        # Even if there's a file under provenance, include=("blocks",)
        # should only invoke the InjectionExtractor. Scaffold a project
        # with a block edit + an arbitrary provenance file entry that
        # the FileExtractor would normally pick up.
        meta = _scaffold_project(tmp_path)
        edited = meta["block_body"] + "# new\n"
        new_block = _block_text("middleware_cors", "MIDDLEWARE_REGISTRATION", edited)
        original_block = _block_text(
            "middleware_cors", "MIDDLEWARE_REGISTRATION", meta["block_body"]
        )
        meta["main_py"].write_text(
            meta["main_py"].read_text().replace(original_block, new_block)
        )
        bundle = harvest_project(tmp_path, include=("blocks",), quiet=True)
        # Every candidate (if any) must be block-kind.
        assert all(c.kind == "block" for c in bundle.candidates)
        # And we still get the block-edit signal.
        assert len(bundle.candidates) >= 1


# ---------------------------------------------------------------------------
# HarvestBundle.write — on-disk layout
# ---------------------------------------------------------------------------


class TestHarvestBundleWrite:
    def test_write_creates_expected_layout(self, tmp_path: Path) -> None:
        meta = _scaffold_project(tmp_path)
        edited = meta["block_body"] + "# new\n"
        new_block = _block_text("middleware_cors", "MIDDLEWARE_REGISTRATION", edited)
        original_block = _block_text(
            "middleware_cors", "MIDDLEWARE_REGISTRATION", meta["block_body"]
        )
        meta["main_py"].write_text(
            meta["main_py"].read_text().replace(original_block, new_block)
        )
        out_dir = tmp_path / "_harvest"
        bundle = harvest_project(tmp_path, out_dir=out_dir, quiet=True)

        # Top-level files.
        assert (out_dir / "manifest.json").is_file()
        assert (out_dir / "README.md").is_file()
        assert (out_dir / "patches").is_dir()

        # Per-fragment patch dir + meta.json + at least one patch file.
        frag_dir = out_dir / "patches" / "middleware_cors"
        assert frag_dir.is_dir()
        assert (frag_dir / "meta.json").is_file()
        patch_files = sorted(frag_dir.glob("*.patch"))
        assert len(patch_files) >= 1
        # The patch filename includes the kind tag.
        assert any(p.name.startswith("0001-block-") for p in patch_files)

        # The manifest.json carries the same candidate list.
        envelope = json.loads((out_dir / "manifest.json").read_text())
        assert envelope["bundle_id"] == bundle.bundle_id
        assert envelope["forge_version"] == bundle.forge_version
        assert len(envelope["candidates"]) == len(bundle.candidates)

    def test_write_empty_bundle_still_creates_structure(self, tmp_path: Path) -> None:
        # A bundle with zero candidates should still produce the
        # manifest + README + empty patches dir so downstream consumers
        # always see the same shape.
        _scaffold_project(tmp_path)
        out_dir = tmp_path / "_harvest"
        bundle = harvest_project(tmp_path, out_dir=out_dir, quiet=True)
        assert bundle.candidates == []
        assert (out_dir / "manifest.json").is_file()
        assert (out_dir / "README.md").is_file()
        assert (out_dir / "patches").is_dir()
        # No fragment subdirectories.
        assert list((out_dir / "patches").iterdir()) == []

    def test_write_bundle_through_method(self, tmp_path: Path) -> None:
        # Smoke test that HarvestBundle.write delegates to the bundle module.
        cand = CandidatePatch(
            fragment="some_fragment",
            backend="api",
            kind="block",
            rel_path="src/foo.py",
            target_path="/tmp/foo.py",
            diff="@@ -1 +1 @@\n-old\n+new\n",
            baseline_sha="abc",
            current_sha="def",
            risk="safe-apply",
            rationale="user added a line",
        )
        bundle = HarvestBundle(
            bundle_id="harvest-test",
            project_root=tmp_path,
            forge_version="0.0.0-test",
            candidates=[cand],
        )
        out_dir = tmp_path / "_harvest"
        bundle.write(out_dir)
        assert (out_dir / "manifest.json").is_file()
        assert (out_dir / "patches" / "some_fragment" / "meta.json").is_file()

    def test_write_bundle_function_directly(self, tmp_path: Path) -> None:
        # Direct call to write_bundle (no HarvestBundle method indirection).
        bundle = HarvestBundle(
            bundle_id="harvest-direct",
            project_root=tmp_path,
            forge_version="0.0.0-test",
            candidates=[],
        )
        out_dir = tmp_path / "_harvest_direct"
        write_bundle(bundle, out_dir)
        assert (out_dir / "manifest.json").is_file()


# ---------------------------------------------------------------------------
# CLI dispatch — _run_harvest end-to-end
# ---------------------------------------------------------------------------


def _harvest_namespace(
    *,
    project_path: str,
    harvest_out: str = ".forge-harvest",
    harvest_scope: str | None = None,
    harvest_include: str = "all",
    harvest_interactive: bool = False,
    quiet: bool = True,
    json_output: bool = False,
) -> Namespace:
    return Namespace(
        project_path=project_path,
        harvest_out=harvest_out,
        harvest_scope=harvest_scope,
        harvest_include=harvest_include,
        harvest_interactive=harvest_interactive,
        quiet=quiet,
        json_output=json_output,
    )


class TestHarvestCLIDispatch:
    def test_cli_runs_against_project(self, tmp_path: Path) -> None:
        meta = _scaffold_project(tmp_path)
        # Edit the block so we get a safe-apply candidate.
        edited = meta["block_body"] + "# new\n"
        new_block = _block_text("middleware_cors", "MIDDLEWARE_REGISTRATION", edited)
        original_block = _block_text(
            "middleware_cors", "MIDDLEWARE_REGISTRATION", meta["block_body"]
        )
        meta["main_py"].write_text(
            meta["main_py"].read_text().replace(original_block, new_block)
        )

        out_dir = tmp_path / "_harvest"
        ns = _harvest_namespace(
            project_path=str(tmp_path),
            harvest_out=str(out_dir),
        )
        rc = _run_harvest(ns)
        assert rc == 0
        assert (out_dir / "manifest.json").is_file()
        envelope = json.loads((out_dir / "manifest.json").read_text())
        assert envelope["candidates"]

    def test_cli_streaming_json_mode(self, tmp_path: Path, capsys) -> None:
        _scaffold_project(tmp_path)
        ns = _harvest_namespace(
            project_path=str(tmp_path),
            harvest_out="-",
        )
        rc = _run_harvest(ns)
        assert rc == 0
        out = capsys.readouterr().out.strip()
        envelope = json.loads(out)
        assert "bundle_id" in envelope
        assert envelope["candidates"] == []

    def test_cli_missing_forge_toml_exit_5(self, tmp_path: Path, capsys) -> None:
        # Empty tmp_path — no forge.toml.
        out_dir = tmp_path / "_harvest"
        ns = _harvest_namespace(
            project_path=str(tmp_path),
            harvest_out=str(out_dir),
        )
        rc = _run_harvest(ns)
        assert rc == 5
        # The dispatcher writes a human error message to stderr in
        # bundle-on-disk mode.
        err = capsys.readouterr().err
        assert "no forge.toml" in err

    def test_cli_missing_forge_toml_json_mode_exit_5(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        ns = _harvest_namespace(
            project_path=str(tmp_path),
            harvest_out="-",
        )
        rc = _run_harvest(ns)
        assert rc == 5
        out = capsys.readouterr().out
        envelope = json.loads(out.strip())
        assert "error" in envelope
        assert "no forge.toml" in envelope["error"]

    def test_cli_conflict_returns_exit_11(self, tmp_path: Path) -> None:
        # Produce a conflict by wiping the sentinels — the
        # InjectionExtractor classifies that as a conflict candidate.
        meta = _scaffold_project(tmp_path)
        meta["main_py"].write_text("# top\n# user replaced everything\n# bottom\n")

        out_dir = tmp_path / "_harvest"
        ns = _harvest_namespace(
            project_path=str(tmp_path),
            harvest_out=str(out_dir),
        )
        rc = _run_harvest(ns)
        # Bundle is still written; exit code surfaces the conflict.
        assert rc == 11
        assert (out_dir / "manifest.json").is_file()

    def test_cli_scope_filter(self, tmp_path: Path) -> None:
        # User edit but scope to a fragment that doesn't exist → exit 0
        # because the candidate list is empty.
        meta = _scaffold_project(tmp_path)
        edited = meta["block_body"] + "# new\n"
        new_block = _block_text("middleware_cors", "MIDDLEWARE_REGISTRATION", edited)
        original_block = _block_text(
            "middleware_cors", "MIDDLEWARE_REGISTRATION", meta["block_body"]
        )
        meta["main_py"].write_text(
            meta["main_py"].read_text().replace(original_block, new_block)
        )
        ns = _harvest_namespace(
            project_path=str(tmp_path),
            harvest_out=str(tmp_path / "_harvest"),
            harvest_scope="nonexistent_fragment",
        )
        rc = _run_harvest(ns)
        assert rc == 0
        envelope = json.loads((tmp_path / "_harvest" / "manifest.json").read_text())
        assert envelope["candidates"] == []
