"""Tests for the applier pipeline composition.

Each applier is stubbed with an in-process spy so we can verify
:class:`FragmentPipeline` invokes them in the canonical order:
files → injection → deps → env.
"""

from __future__ import annotations

from pathlib import Path

from forge.appliers import (
    FragmentDepsApplier,
    FragmentEnvApplier,
    FragmentFileApplier,
    FragmentInjectionApplier,
    FragmentPipeline,
    FragmentPlan,
)
from forge.config import BackendConfig, BackendLanguage
from forge.fragment_context import FragmentContext
from forge.fragments import FragmentImplSpec


class _Spy:
    """Applier drop-in that records the order of calls."""

    def __init__(self, name: str, log: list[str]) -> None:
        self.name = name
        self.log = log

    def apply(self, ctx: FragmentContext, plan: FragmentPlan) -> None:
        self.log.append(self.name)


def _mk_ctx(tmp_path: Path) -> FragmentContext:
    return FragmentContext(
        backend_config=BackendConfig(name="api", project_name="p", language=BackendLanguage.PYTHON),
        backend_dir=tmp_path,
        project_root=tmp_path,
        options={},
        provenance=None,
    )


class TestPipelineOrdering:
    def test_default_pipeline_runs_files_then_injection_then_deps_then_env(
        self, tmp_path: Path
    ) -> None:
        log: list[str] = []
        pipeline = FragmentPipeline(
            files=_Spy("files", log),  # type: ignore[arg-type]
            injection=_Spy("injection", log),  # type: ignore[arg-type]
            deps=_Spy("deps", log),  # type: ignore[arg-type]
            env=_Spy("env", log),  # type: ignore[arg-type]
        )

        frag = tmp_path / "spy_fragment"
        frag.mkdir()
        impl = FragmentImplSpec(fragment_dir=str(frag))
        pipeline.run(_mk_ctx(tmp_path), impl, "spy_fragment")

        assert log == ["files", "injection", "deps", "env"]

    def test_default_factory_returns_real_appliers(self) -> None:
        pipeline = FragmentPipeline.default()
        assert isinstance(pipeline.files, FragmentFileApplier)
        assert isinstance(pipeline.injection, FragmentInjectionApplier)
        assert isinstance(pipeline.deps, FragmentDepsApplier)
        assert isinstance(pipeline.env, FragmentEnvApplier)


class TestApplierShortCircuits:
    """Each real applier is a no-op when its part of the plan is empty."""

    def test_file_applier_no_op_on_empty_plan(self, tmp_path: Path) -> None:
        plan = FragmentPlan(
            fragment_dir=tmp_path,
            files_dir=None,
            injections=(),
            dependencies=(),
            env_vars=(),
            feature_key="x",
        )
        FragmentFileApplier().apply(_mk_ctx(tmp_path), plan)
        # No-op on empty files_dir — no files written.
        assert list(tmp_path.iterdir()) == []

    def test_injection_applier_no_op_on_empty_plan(self, tmp_path: Path) -> None:
        plan = FragmentPlan(
            fragment_dir=tmp_path,
            files_dir=None,
            injections=(),
            dependencies=(),
            env_vars=(),
            feature_key="x",
        )
        FragmentInjectionApplier().apply(_mk_ctx(tmp_path), plan)

    def test_deps_applier_no_op_on_empty_plan(self, tmp_path: Path) -> None:
        plan = FragmentPlan(
            fragment_dir=tmp_path,
            files_dir=None,
            injections=(),
            dependencies=(),
            env_vars=(),
            feature_key="x",
        )
        # Would raise FragmentError(DEPS_FILE_MISSING) if it tried to open
        # a pyproject.toml; the empty-deps short-circuit prevents that.
        FragmentDepsApplier().apply(_mk_ctx(tmp_path), plan)

    def test_env_applier_no_op_on_empty_plan(self, tmp_path: Path) -> None:
        plan = FragmentPlan(
            fragment_dir=tmp_path,
            files_dir=None,
            injections=(),
            dependencies=(),
            env_vars=(),
            feature_key="x",
        )
        FragmentEnvApplier().apply(_mk_ctx(tmp_path), plan)
        # No .env.example written.
        assert not (tmp_path / ".env.example").exists()
