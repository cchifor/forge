"""Tests for forge/updater.py — the engine behind `forge --update`."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from forge.config import (
    BackendConfig,
    BackendLanguage,
    FrontendConfig,
    FrontendFramework,
    ProjectConfig,
)
from forge.errors import GeneratorError
from forge.forge_toml import read_forge_toml, write_forge_toml
from forge.updater import _infer_backends, update_project


@pytest.fixture
def fake_project(tmp_path: Path) -> Path:
    """Build a stub forge-generated project without running Copier.

    Includes every marker the default-enabled Options target
    (correlation_id, pii_redaction, security_headers, rate_limit), so
    the resolver can expand defaults without the injector raising on
    missing files.
    """
    root = tmp_path / "proj"
    backend = root / "services" / "backend"
    (backend / "src" / "app" / "core").mkdir(parents=True)
    (backend / "src" / "app" / "middleware").mkdir(parents=True)
    (backend / "pyproject.toml").write_text(
        '[project]\nname="x"\nversion="0.1"\ndependencies = []\n',
        encoding="utf-8",
    )
    (backend / ".env.example").write_text("", encoding="utf-8")

    main_py = backend / "src" / "app" / "main.py"
    main_py.write_text(
        "\n".join(
            [
                "# FORGE:MIDDLEWARE_IMPORTS",
                "",
                "def create_app():",
                "    # FORGE:MIDDLEWARE_REGISTRATION",
                "    # FORGE:ROUTER_REGISTRATION",
                "    # FORGE:EXCEPTION_HANDLERS",
                "    # FORGE:APP_POST_CONFIGURE",
                "    return None",
                "",
            ]
        ),
        encoding="utf-8",
    )

    lifecycle = backend / "src" / "app" / "core" / "lifecycle.py"
    lifecycle.write_text(
        "\n".join(
            [
                "def bootstrap():",
                "    # FORGE:LIFECYCLE_STARTUP",
                "    pass",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return root


class TestInferBackends:
    def test_finds_python_backend(self, fake_project: Path) -> None:
        backends = _infer_backends(fake_project)
        assert len(backends) == 1
        assert backends[0].language == BackendLanguage.PYTHON
        assert backends[0].name == "backend"

    def test_ignores_dirs_without_marker(self, fake_project: Path) -> None:
        (fake_project / "services" / "rogue").mkdir()  # empty, no marker file
        backends = _infer_backends(fake_project)
        assert {b.name for b in backends} == {"backend"}

    def test_missing_services_dir_returns_empty(self, tmp_path: Path) -> None:
        assert _infer_backends(tmp_path) == []


class TestUpdateProject:
    def test_refuses_without_forge_toml(self, tmp_path: Path) -> None:
        with pytest.raises(GeneratorError, match="No forge.toml"):
            update_project(tmp_path)

    def test_restamps_version_and_option_table(self, fake_project: Path) -> None:
        write_forge_toml(
            fake_project / "forge.toml",
            version="0.0.1",  # intentionally stale
            project_name="proj",
            templates={"python": "services/python-service-template"},
            options={"middleware.correlation_id": "always-on"},
        )

        summary = update_project(fake_project, quiet=True)

        after = read_forge_toml(fake_project / "forge.toml")
        assert after.version != "0.0.1"  # re-stamped to current forge version
        # Re-stamp writes every registered option's resolved value, so the
        # user's value is preserved and any default the registry carries
        # is added.
        assert after.options["middleware.correlation_id"] == "always-on"
        assert summary["backends"] == ["backend"]
        assert "correlation_id" in summary["fragments_applied"]

    def test_injection_is_idempotent_across_runs(self, fake_project: Path) -> None:
        """Calling update_project twice produces byte-identical files."""
        write_forge_toml(
            fake_project / "forge.toml",
            version="0.1.0",
            project_name="proj",
            templates={"python": "services/python-service-template"},
            options={"middleware.correlation_id": "always-on"},
        )

        update_project(fake_project, quiet=True)
        main_py = fake_project / "services" / "backend" / "src" / "app" / "main.py"
        snapshot = main_py.read_text(encoding="utf-8")

        update_project(fake_project, quiet=True)
        assert main_py.read_text(encoding="utf-8") == snapshot

    def test_legacy_forge_toml_rejected(self, fake_project: Path) -> None:
        """A pre-Option forge.toml (``[forge.features]``) is a hard error —
        the refactor is a hard cutover, no silent auto-migration.
        """
        manifest = fake_project / "forge.toml"
        manifest.write_text(
            "\n".join(
                [
                    "[forge]",
                    'version = "0.1.0"',
                    'project_name = "proj"',
                    "[forge.templates]",
                    'python = "services/python-service-template"',
                    "[forge.features]",
                    'enabled = ["correlation_id"]',
                    "",
                ]
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="legacy"):
            read_forge_toml(manifest)


class TestIntegrationAgainstGenerator:
    """End-to-end: use the real generator, then run update on the output."""

    def test_full_generate_then_update(self, tmp_path: Path) -> None:
        from forge.generator import generate

        cfg = ProjectConfig(
            project_name="updatable",
            backends=[
                BackendConfig(
                    name="backend",
                    project_name="updatable",
                    language=BackendLanguage.PYTHON,
                ),
            ],
            frontend=FrontendConfig(framework=FrontendFramework.NONE, project_name="updatable"),
            options={"middleware.rate_limit": True},
            output_dir=str(tmp_path),
        )
        project_root = generate(cfg, quiet=True)

        main_py = project_root / "services" / "backend" / "src" / "app" / "main.py"
        before = main_py.read_text(encoding="utf-8")

        summary = update_project(project_root, quiet=True)

        after = main_py.read_text(encoding="utf-8")
        # Byte-identical: sentinels let re-injection be a no-op.
        assert before == after
        assert "rate_limit" in summary["fragments_applied"]
        # P0.1: default mode is "merge", no conflicts on a clean re-apply.
        assert summary["update_mode"] == "merge"
        assert summary["file_conflicts"] == 0

        # Cleanup (some Windows filesystems hold locks on the venv, so
        # shutil.rmtree may need ignore_errors).
        shutil.rmtree(project_root, ignore_errors=True)


# ---------------------------------------------------------------------------
# P0.1 — file-level three-way merge integration tests
# ---------------------------------------------------------------------------


def _find_fragment_file(project_root: Path) -> Path | None:
    """Return any fragment-authored file under the project, for merge tests.

    The integration tests need a known fragment-emitted file to mutate
    and re-apply against. Walks the manifest's provenance table for the
    first ``origin=fragment`` entry that resolves to an existing path.
    Returns ``None`` if no such file exists in the generated project
    (the test should xfail/skip rather than misreport).
    """
    from forge.forge_toml import read_forge_toml  # noqa: PLC0415

    data = read_forge_toml(project_root / "forge.toml")
    for rel, entry in data.provenance.items():
        if entry.get("origin") != "fragment":
            continue
        path = project_root / rel
        if path.is_file() and path.suffix in (".py", ".js", ".ts", ".rs", ".md"):
            return path
    return None


class TestUpdateModeMatrix:
    """Behaviour of --mode={merge,skip,overwrite} against a user-edited file."""

    @pytest.fixture
    def generated_project(self, tmp_path: Path) -> Path:
        """Generate a real project with a few fragments enabled."""
        from forge.generator import generate  # noqa: PLC0415

        cfg = ProjectConfig(
            project_name="merge-test",
            backends=[
                BackendConfig(
                    name="backend",
                    project_name="merge-test",
                    language=BackendLanguage.PYTHON,
                ),
            ],
            frontend=FrontendConfig(
                framework=FrontendFramework.NONE, project_name="merge-test"
            ),
            options={
                "middleware.rate_limit": True,
                "middleware.correlation_id": "always-on",
            },
            output_dir=str(tmp_path),
        )
        project_root = generate(cfg, quiet=True)
        yield project_root
        shutil.rmtree(project_root, ignore_errors=True)

    def test_merge_mode_preserves_user_edit_when_fragment_unchanged(
        self, generated_project: Path
    ) -> None:
        """User edit + fragment unchanged → ``skipped-no-change``: edit survives."""
        target = _find_fragment_file(generated_project)
        if target is None:
            pytest.skip("no fragment-authored file in generated project")

        # Simulate a user edit.
        target.write_text(
            "# user edit -- should survive update\nprint('hello')\n",
            encoding="utf-8",
        )

        summary = update_project(generated_project, quiet=True, update_mode="merge")
        assert summary["file_conflicts"] == 0
        assert "user edit -- should survive" in target.read_text(encoding="utf-8")

    def test_skip_mode_preserves_user_edit(self, generated_project: Path) -> None:
        """``--mode skip`` reproduces pre-1.1 behaviour: user files are
        preserved unconditionally, regardless of merge baselines."""
        target = _find_fragment_file(generated_project)
        if target is None:
            pytest.skip("no fragment-authored file in generated project")

        target.write_text("# pre-1.1 skip path\n", encoding="utf-8")

        summary = update_project(generated_project, quiet=True, update_mode="skip")
        assert summary["update_mode"] == "skip"
        assert summary["file_conflicts"] == 0
        assert target.read_text(encoding="utf-8") == "# pre-1.1 skip path\n"

    def test_overwrite_mode_clobbers_user_edit(
        self, generated_project: Path
    ) -> None:
        """``--mode overwrite`` is the escape hatch: fragment content wins."""
        target = _find_fragment_file(generated_project)
        if target is None:
            pytest.skip("no fragment-authored file in generated project")

        sentinel = "# user edit that should NOT survive overwrite\n"
        target.write_text(sentinel, encoding="utf-8")

        summary = update_project(
            generated_project, quiet=True, update_mode="overwrite"
        )
        assert summary["update_mode"] == "overwrite"
        # Either the file matches a fragment-authored version (sentinel
        # gone) or the file is a no-op match — either way, the user
        # marker has not survived.
        assert sentinel not in target.read_text(encoding="utf-8")

    def test_summary_carries_update_mode_and_conflict_count(
        self, generated_project: Path
    ) -> None:
        """Summary always exposes the mode chosen and the conflict tally,
        so callers can branch on a clean re-apply vs. a conflict-heavy one
        without parsing log output.
        """
        summary = update_project(generated_project, quiet=True, update_mode="merge")
        assert summary["update_mode"] == "merge"
        assert isinstance(summary["file_conflicts"], int)
        assert summary["file_conflicts"] >= 0


class TestUpdateModeConflict:
    """Forced-conflict scenarios: user edit + fragment-baseline drift."""

    @pytest.fixture
    def generated_project_with_drifted_baseline(self, tmp_path: Path) -> Path:
        """Generate a project, then mutate the manifest baseline so the
        next ``--update`` sees ``baseline != current != new`` for one file.

        Yields the project root and the rel-path of the file we
        engineered a conflict on.
        """
        from forge.forge_toml import read_forge_toml, write_forge_toml  # noqa: PLC0415
        from forge.generator import generate  # noqa: PLC0415

        cfg = ProjectConfig(
            project_name="conflict-test",
            backends=[
                BackendConfig(
                    name="backend",
                    project_name="conflict-test",
                    language=BackendLanguage.PYTHON,
                ),
            ],
            frontend=FrontendConfig(
                framework=FrontendFramework.NONE, project_name="conflict-test"
            ),
            options={"middleware.rate_limit": True},
            output_dir=str(tmp_path),
        )
        project_root = generate(cfg, quiet=True)

        target = _find_fragment_file(project_root)
        if target is None:
            pytest.skip("no fragment-authored file in generated project")

        # Mutate the manifest's recorded baseline SHA to a stale value
        # so file_three_way_decide sees baseline != current != new.
        # 64 zeroes is a valid hex digest that no real file will hash to.
        manifest = project_root / "forge.toml"
        data = read_forge_toml(manifest)
        rel = target.relative_to(project_root).as_posix()
        provenance = dict(data.provenance)
        if rel not in provenance:
            pytest.skip("target file has no provenance record to drift")
        entry = dict(provenance[rel])
        entry["sha256"] = "0" * 64
        provenance[rel] = entry

        write_forge_toml(
            manifest,
            version=data.version,
            project_name=data.project_name or "conflict-test",
            templates=dict(data.templates),
            options=dict(data.options),
            provenance=provenance,
            merge_blocks=dict(data.merge_blocks),
        )

        # User edit on disk → current_sha distinct from both baseline
        # (now zeros) and new (whatever the fragment ships).
        target.write_text(
            "# user edit during conflict scenario\nfoo = 'bar'\n",
            encoding="utf-8",
        )

        try:
            yield (project_root, rel)
        finally:
            shutil.rmtree(project_root, ignore_errors=True)

    def test_merge_mode_emits_sidecar_on_three_way_conflict(
        self,
        generated_project_with_drifted_baseline: tuple[Path, str],
    ) -> None:
        """User edit + fragment ≠ baseline + fragment ≠ current → conflict.

        The decision function sees three distinct hashes: stale baseline
        (zeros), user-edited current, and fragment-authored new.
        ``file_three_way_decide`` returns ``"conflict"``; the applier
        writes a ``.forge-merge`` sidecar; the target stays untouched.
        """
        project_root, rel = generated_project_with_drifted_baseline
        target = project_root / rel

        before = target.read_text(encoding="utf-8")
        summary = update_project(project_root, quiet=True, update_mode="merge")

        # User content untouched.
        assert target.read_text(encoding="utf-8") == before
        # Sidecar present — text suffix because the file is .py-style.
        sidecar = target.with_suffix(target.suffix + ".forge-merge")
        assert sidecar.exists()
        assert "merge by hand" in sidecar.read_text(encoding="utf-8").lower()
        # Summary surfaces the count.
        assert summary["file_conflicts"] >= 1


class TestUpdateModeUserDeleted:
    """User deleted a fragment file → re-emit on update."""

    def test_merge_mode_reemits_user_deleted_fragment_file(
        self, tmp_path: Path
    ) -> None:
        from forge.generator import generate  # noqa: PLC0415

        cfg = ProjectConfig(
            project_name="deleted-test",
            backends=[
                BackendConfig(
                    name="backend",
                    project_name="deleted-test",
                    language=BackendLanguage.PYTHON,
                ),
            ],
            frontend=FrontendConfig(
                framework=FrontendFramework.NONE, project_name="deleted-test"
            ),
            options={"middleware.rate_limit": True},
            output_dir=str(tmp_path),
        )
        project_root = generate(cfg, quiet=True)
        try:
            target = _find_fragment_file(project_root)
            if target is None:
                pytest.skip("no fragment-authored file in generated project")

            # User deletes the file. The decision is "applied" — disabling
            # a fragment is the documented way to remove its files; bare
            # deletion gets the file regenerated.
            target.unlink()
            assert not target.exists()

            update_project(project_root, quiet=True, update_mode="merge")

            assert target.exists()
        finally:
            shutil.rmtree(project_root, ignore_errors=True)


class TestUpdateModeUserModifiedOutput:
    """Cover the per-mode user_modified summary output paths added by P0.1.

    Each mode prints a different help line when classification turns up
    user-modified files; the lines guide the operator on what merge will
    actually do. Exercising each branch keeps the coverage gate happy
    *and* protects against regressions in the operator-facing UX.
    """

    def test_user_modified_summary_in_merge_mode(
        self, tmp_path: Path, capsys
    ) -> None:
        from forge.forge_toml import read_forge_toml, write_forge_toml
        from forge.generator import generate

        cfg = ProjectConfig(
            project_name="usermod",
            backends=[
                BackendConfig(
                    name="backend",
                    project_name="usermod",
                    language=BackendLanguage.PYTHON,
                ),
            ],
            frontend=FrontendConfig(
                framework=FrontendFramework.NONE, project_name="usermod"
            ),
            options={"middleware.rate_limit": True},
            output_dir=str(tmp_path),
        )
        project_root = generate(cfg, quiet=True)
        try:
            # Edit any fragment file to make classification flag it.
            data = read_forge_toml(project_root / "forge.toml")
            target_rel = next(
                rel
                for rel, entry in data.provenance.items()
                if entry.get("origin") == "fragment"
                and (project_root / rel).is_file()
            )
            (project_root / target_rel).write_text(
                "# user edit\n", encoding="utf-8"
            )

            update_project(project_root, quiet=False, update_mode="merge")
            captured = capsys.readouterr().out
            assert "modified since last generate" in captured
            assert "mode=merge" in captured
            assert "three-way decide" in captured
        finally:
            shutil.rmtree(project_root, ignore_errors=True)

    def test_user_modified_summary_in_skip_mode(
        self, tmp_path: Path, capsys
    ) -> None:
        from forge.forge_toml import read_forge_toml
        from forge.generator import generate

        cfg = ProjectConfig(
            project_name="usermod-skip",
            backends=[
                BackendConfig(
                    name="backend",
                    project_name="usermod-skip",
                    language=BackendLanguage.PYTHON,
                ),
            ],
            frontend=FrontendConfig(
                framework=FrontendFramework.NONE, project_name="usermod-skip"
            ),
            options={"middleware.rate_limit": True},
            output_dir=str(tmp_path),
        )
        project_root = generate(cfg, quiet=True)
        try:
            data = read_forge_toml(project_root / "forge.toml")
            target_rel = next(
                rel
                for rel, entry in data.provenance.items()
                if entry.get("origin") == "fragment"
                and (project_root / rel).is_file()
            )
            (project_root / target_rel).write_text(
                "# user edit\n", encoding="utf-8"
            )

            update_project(project_root, quiet=False, update_mode="skip")
            captured = capsys.readouterr().out
            assert "mode=skip" in captured
            assert "preserved unconditionally" in captured
        finally:
            shutil.rmtree(project_root, ignore_errors=True)

    def test_user_modified_summary_in_overwrite_mode(
        self, tmp_path: Path, capsys
    ) -> None:
        from forge.forge_toml import read_forge_toml
        from forge.generator import generate

        cfg = ProjectConfig(
            project_name="usermod-over",
            backends=[
                BackendConfig(
                    name="backend",
                    project_name="usermod-over",
                    language=BackendLanguage.PYTHON,
                ),
            ],
            frontend=FrontendConfig(
                framework=FrontendFramework.NONE, project_name="usermod-over"
            ),
            options={"middleware.rate_limit": True},
            output_dir=str(tmp_path),
        )
        project_root = generate(cfg, quiet=True)
        try:
            data = read_forge_toml(project_root / "forge.toml")
            target_rel = next(
                rel
                for rel, entry in data.provenance.items()
                if entry.get("origin") == "fragment"
                and (project_root / rel).is_file()
            )
            (project_root / target_rel).write_text(
                "# user edit\n", encoding="utf-8"
            )

            update_project(project_root, quiet=False, update_mode="overwrite")
            captured = capsys.readouterr().out
            assert "mode=overwrite" in captured
            assert "clobbered" in captured
        finally:
            shutil.rmtree(project_root, ignore_errors=True)


class TestUpdateUninstallPath:
    """Cover the disabled-fragment uninstall logging branch.

    Run a generate → tweak forge.toml's options to disable a fragment
    that's currently in the plan → run update → confirm the uninstaller
    fires. Exercises the lines around the ``uninstall_fragment`` call
    that the prior tests skip past (no fragments ever leave the plan).
    """

    def test_uninstall_logs_when_fragment_disabled(
        self, tmp_path: Path, capsys
    ) -> None:
        from forge.forge_toml import read_forge_toml, write_forge_toml
        from forge.generator import generate

        cfg = ProjectConfig(
            project_name="uninst",
            backends=[
                BackendConfig(
                    name="backend",
                    project_name="uninst",
                    language=BackendLanguage.PYTHON,
                ),
            ],
            frontend=FrontendConfig(
                framework=FrontendFramework.NONE, project_name="uninst"
            ),
            options={"middleware.rate_limit": True, "platform.webhooks": True},
            output_dir=str(tmp_path),
        )
        project_root = generate(cfg, quiet=True)
        try:
            # Disable webhooks: rewrite forge.toml without it.
            data = read_forge_toml(project_root / "forge.toml")
            new_options = dict(data.options)
            new_options["platform.webhooks"] = False
            write_forge_toml(
                project_root / "forge.toml",
                version=data.version,
                project_name=data.project_name or "uninst",
                templates=dict(data.templates),
                options=new_options,
                provenance=dict(data.provenance),
                merge_blocks=dict(data.merge_blocks),
            )

            summary = update_project(project_root, quiet=False)
            captured = capsys.readouterr().out
            # The uninstaller's log lines must reach the operator.
            assert "uninstalling" in captured
            uninstalled = summary.get("uninstalled", [])
            uninstalled_names = [
                entry.get("fragment") if isinstance(entry, dict) else None
                for entry in uninstalled
            ]
            assert "webhooks" in uninstalled_names
        finally:
            shutil.rmtree(project_root, ignore_errors=True)


class TestUpdaterResolveFailure:
    """Cover the OptionsError re-raise on a corrupt forge.toml ([forge.options]
    referencing an option path the registry no longer recognises)."""

    def test_resolve_failure_wraps_in_options_error(
        self, fake_project: Path
    ) -> None:
        from forge.errors import OptionsError

        # Stamp a forge.toml that references a path no Option claims.
        # The resolver re-raises the underlying registry error wrapped
        # in OptionsError so the CLI envelope stays informative.
        write_forge_toml(
            fake_project / "forge.toml",
            version="1.0.0",
            project_name="corrupt",
            templates={"python": "services/python-service-template"},
            options={"this.path.doesnt.exist": True},
        )
        with pytest.raises(OptionsError, match="resolve option plan"):
            update_project(fake_project, quiet=True)


class TestUpdateModeNoBaseline:
    """Pre-1.1 / hand-authored projects with no provenance baselines."""

    def test_merge_mode_treats_untracked_files_as_user_authored(
        self, fake_project: Path
    ) -> None:
        """A file present on disk but absent from the manifest provenance
        hits the ``no-baseline`` row of the decision table — preserved
        as user-authored. The fixture's hand-built project has no
        ``[forge.provenance]`` entries, exercising this path.
        """
        write_forge_toml(
            fake_project / "forge.toml",
            version="1.0.0",
            project_name="proj",
            templates={"python": "services/python-service-template"},
            options={"middleware.correlation_id": "always-on"},
        )
        # Hand-author a "fragment-shaped" file to confirm it survives.
        sentinel = fake_project / "services" / "backend" / "src" / "app" / "user_owned.py"
        sentinel.write_text("# user authored before forge knew\n", encoding="utf-8")

        summary = update_project(fake_project, quiet=True, update_mode="merge")
        # Default mode + empty provenance → file untouched.
        assert sentinel.read_text(encoding="utf-8") == "# user authored before forge knew\n"
        assert summary["file_conflicts"] == 0
