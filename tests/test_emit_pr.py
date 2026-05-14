"""Tests for ``forge --emit-pr`` (Phase 6 close of the bidirectional-sync plan).

Covers the emit-pr helper end-to-end:

* :func:`forge.sync.project_to_forge.emit_pr.emit_pr` — branch + commit
  + (optional) gh pr create lifecycle.
* :class:`EmitPrReport` — per-candidate dispositions, JSON shape,
  human-render output.
* CLI dispatch: ``forge --harvest --emit-pr=branch --forge-repo PATH``
  chains the emit step after harvest writes the bundle. JSON / human
  output modes are tested.

Each test scaffolds a minimal forge_repo (tmp_path with .git/) and a
single-candidate bundle (files-kind for simplicity) so the assertions
focus on the branch + commit lifecycle rather than the per-kind
applier (covered exhaustively in tests/test_apply_bundle_deps_env.py
and tests/test_harvest_invariants.py).
"""

from __future__ import annotations

import importlib
import json
import subprocess
from argparse import Namespace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from forge.cli.commands.harvest import _run_harvest
from forge.config import BackendLanguage
from forge.extractors.pipeline import CandidatePatch
from forge.fragments import FRAGMENT_REGISTRY, Fragment, FragmentImplSpec
from forge.sync.project_to_forge.emit_pr import (
    EmitPrEntry,
    EmitPrReport,
    emit_pr,
)
from forge.sync.project_to_forge.harvester import HarvestBundle

# The package's ``__init__`` exposes ``emit_pr`` (function) as an
# attribute of ``forge.sync.project_to_forge``, which shadows the
# module name. We grab the module via importlib so subprocess-runner
# monkeypatches target the right object.
emit_pr_module = importlib.import_module("forge.sync.project_to_forge.emit_pr")


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _init_forge_repo(repo: Path) -> None:
    """Initialise a tmp git repo with a minimal forge tree.

    Creates a ``forge/features/<name>/`` directory the synthetic
    fragment can register against, plus a seed commit so ``git status``
    starts clean.
    """
    repo.mkdir(parents=True, exist_ok=True)
    # Set per-test author so commits don't depend on the developer's
    # global git config (CI environments often have no global config).
    for cmd in (
        ["git", "init", "--initial-branch=main"],
        ["git", "config", "user.email", "test@forge.invalid"],
        ["git", "config", "user.name", "Forge Test"],
        ["git", "config", "commit.gpgsign", "false"],
    ):
        subprocess.run(cmd, cwd=str(repo), check=True, capture_output=True)
    (repo / "README.md").write_text("# test forge clone\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=str(repo), check=True, capture_output=True
    )


def _register_synthetic_fragment(
    name: str,
    *,
    fragment_dir: str = "_synthetic_emit",
    languages: tuple[BackendLanguage, ...] = (BackendLanguage.PYTHON,),
) -> Fragment:
    """Register a synthetic fragment in the in-process registry."""
    impls: dict[BackendLanguage, FragmentImplSpec] = {}
    for lang in languages:
        impls[lang] = FragmentImplSpec(fragment_dir=fragment_dir)
    fragment = Fragment(name=name, implementations=impls)
    was_frozen = getattr(FRAGMENT_REGISTRY, "frozen", False)
    if was_frozen:
        FRAGMENT_REGISTRY.frozen = False
    FRAGMENT_REGISTRY[name] = fragment
    if was_frozen:
        FRAGMENT_REGISTRY.frozen = True
    return fragment


def _unregister_fragment(name: str) -> None:
    was_frozen = getattr(FRAGMENT_REGISTRY, "frozen", False)
    if was_frozen:
        FRAGMENT_REGISTRY.frozen = False
    FRAGMENT_REGISTRY.pop(name, None)
    if was_frozen:
        FRAGMENT_REGISTRY.frozen = True


def _scaffold_synthetic_fragment_files(
    forge_repo: Path,
    *,
    fragment_dir: str = "_synthetic_emit",
    rel_path: str = "src/app/main.py",
    body: str = "# original\n",
) -> Path:
    """Lay down the fragment's ``files/`` directory inside ``forge_repo``.

    The applier looks up ``<forge_repo>/forge/templates/_fragments/<dir>/files/``
    or ``<forge_repo>/forge/features/<dir>/files/`` — we use the
    ``_fragments`` location to match the registry's default lookup.
    """
    files_dir = forge_repo / "forge" / "templates" / "_fragments" / fragment_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    target = files_dir / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


def _file_candidate(
    *,
    fragment: str,
    project_root: Path,
    rel_path: str = "src/app/main.py",
    body: str = "# edited by the user\n",
    risk: str = "safe-apply",
) -> CandidatePatch:
    """Construct a files-kind CandidatePatch backed by a real file on disk.

    The applier reads ``cand.target_path`` to source the new bytes, so
    we materialise that file under ``project_root`` first.
    """
    src = project_root / "services" / "api" / rel_path
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(body, encoding="utf-8")
    return CandidatePatch(
        fragment=fragment,
        backend="api",
        kind="files",
        rel_path=rel_path,
        target_path=str(src),
        diff="--- a\n+++ b\n@@\n+# user edit\n",
        baseline_sha="0" * 64,
        current_sha="1" * 64,
        risk=risk,
        rationale="user edited file",
        current_body=body,
    )


def _bundle_with(
    candidates: list[CandidatePatch],
    *,
    project_root: Path,
    bundle_id: str = "harvest-20260514T120000Z-deadbeef",
) -> HarvestBundle:
    """Build a HarvestBundle wrapping the given candidates."""
    return HarvestBundle(
        bundle_id=bundle_id,
        project_root=project_root,
        forge_version="1.2.0-test",
        candidates=candidates,
    )


def _git_log_subjects(repo: Path) -> list[str]:
    """Return commit subjects on the current branch (newest first)."""
    result = subprocess.run(
        ["git", "log", "--format=%s"],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _git_current_branch(repo: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Branch mode — happy path
# ---------------------------------------------------------------------------


class TestEmitPrBranchModeHappyPath:
    def test_branch_mode_commits_each_candidate_atomically(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        _init_forge_repo(forge_repo)
        fragment_name = "test_emit_branch"
        _scaffold_synthetic_fragment_files(forge_repo)
        _register_synthetic_fragment(fragment_name)
        # Seed-commit the fragment's pre-edit body so subsequent applies
        # produce a real git delta.
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(forge_repo),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "seed fragment files"],
            cwd=str(forge_repo),
            check=True,
            capture_output=True,
        )

        try:
            project_root = tmp_path / "project"
            project_root.mkdir()
            bundle = _bundle_with(
                [
                    _file_candidate(
                        fragment=fragment_name,
                        project_root=project_root,
                        rel_path="src/app/main.py",
                        body="# user edit 1\n",
                    ),
                    _file_candidate(
                        fragment=fragment_name,
                        project_root=project_root,
                        rel_path="src/app/utils.py",
                        body="# user added utility\n",
                    ),
                ],
                project_root=project_root,
            )
            # Materialise the second target on disk so the applier finds
            # the source file. (Note: _scaffold_synthetic_fragment_files
            # already created main.py; utils.py needs its own files/
            # entry so the applier writes it under the fragment.)
            _scaffold_synthetic_fragment_files(
                forge_repo, rel_path="src/app/utils.py", body="# old\n"
            )
            subprocess.run(
                ["git", "add", "-A"],
                cwd=str(forge_repo),
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "seed utils"],
                cwd=str(forge_repo),
                check=True,
                capture_output=True,
            )

            report = emit_pr(bundle, forge_repo, mode="branch", quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        # No pre-condition errors.
        assert not report.errors, report.errors
        # Branch created.
        assert report.branch_name == f"harvest/{bundle.bundle_id}"
        assert _git_current_branch(forge_repo) == report.branch_name
        # Two candidates → two commits (plus the two seed commits + initial).
        assert report.committed == 2, [(e.action, e.reason) for e in report.entries]
        subjects = _git_log_subjects(forge_repo)
        # The first two subjects are the harvest commits (newest first).
        assert any(f"harvest({fragment_name}): files src/app/main.py" in s for s in subjects)
        assert any(f"harvest({fragment_name}): files src/app/utils.py" in s for s in subjects)
        # PR url is empty in branch mode.
        assert report.pr_url == ""

    def test_branch_mode_records_files_touched_per_entry(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        _init_forge_repo(forge_repo)
        fragment_name = "test_emit_branch_touched"
        _scaffold_synthetic_fragment_files(forge_repo)
        _register_synthetic_fragment(fragment_name)
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(forge_repo),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "seed"],
            cwd=str(forge_repo),
            check=True,
            capture_output=True,
        )
        try:
            project_root = tmp_path / "project"
            project_root.mkdir()
            bundle = _bundle_with(
                [
                    _file_candidate(
                        fragment=fragment_name,
                        project_root=project_root,
                    )
                ],
                project_root=project_root,
            )
            report = emit_pr(bundle, forge_repo, mode="branch", quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.committed == 1
        entry = report.entries[0]
        assert entry.action == "committed"
        assert entry.commit_sha is not None
        assert len(entry.commit_sha) == 40  # full SHA
        # The applier wrote forge/templates/_fragments/.../files/src/app/main.py.
        assert any("main.py" in path for path in entry.files_touched)


# ---------------------------------------------------------------------------
# Github mode — happy path via subprocess stub
# ---------------------------------------------------------------------------


class TestEmitPrGithubModeHappyPath:
    def test_github_mode_invokes_gh_and_captures_pr_url(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        _init_forge_repo(forge_repo)
        fragment_name = "test_emit_gh_happy"
        _scaffold_synthetic_fragment_files(forge_repo)
        _register_synthetic_fragment(fragment_name)
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(forge_repo),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "seed"],
            cwd=str(forge_repo),
            check=True,
            capture_output=True,
        )

        # Stub the subprocess runner: real git commands pass through;
        # any ``gh`` invocation is fielded by our fake.
        real_runner = emit_pr_module._run_subprocess

        def fake_runner(cmd, *, cwd):  # type: ignore[no-untyped-def]
            if cmd and cmd[0] == "gh":
                if cmd[1:3] == ["--version"]:
                    return 0, "gh version 2.40.0\n", ""
                if cmd[1:3] == ["auth", "status"]:
                    return 0, "Logged in\n", ""
                if cmd[1:3] == ["pr", "create"]:
                    return 0, "https://github.com/forge/forge/pull/42\n", ""
                return 1, "", f"unexpected gh {cmd[1:]}"
            return real_runner(cmd, cwd=cwd)

        try:
            project_root = tmp_path / "project"
            project_root.mkdir()
            bundle = _bundle_with(
                [_file_candidate(fragment=fragment_name, project_root=project_root)],
                project_root=project_root,
            )
            with patch.object(emit_pr_module, "_run_subprocess", side_effect=fake_runner):
                report = emit_pr(bundle, forge_repo, mode="github", quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert not report.errors, report.errors
        assert report.committed == 1
        assert report.pr_url == "https://github.com/forge/forge/pull/42"

    def test_github_mode_uses_custom_pr_title(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        _init_forge_repo(forge_repo)
        fragment_name = "test_emit_gh_title"
        _scaffold_synthetic_fragment_files(forge_repo)
        _register_synthetic_fragment(fragment_name)
        subprocess.run(["git", "add", "-A"], cwd=str(forge_repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "seed"], cwd=str(forge_repo), check=True, capture_output=True
        )

        observed_titles: list[str] = []
        real_runner = emit_pr_module._run_subprocess

        def fake_runner(cmd, *, cwd):  # type: ignore[no-untyped-def]
            if cmd and cmd[0] == "gh":
                if cmd[1:3] == ["--version"]:
                    return 0, "gh version 2.40.0\n", ""
                if cmd[1:3] == ["auth", "status"]:
                    return 0, "Logged in\n", ""
                if cmd[1:3] == ["pr", "create"]:
                    # The title arg is right after --title.
                    if "--title" in cmd:
                        idx = cmd.index("--title")
                        observed_titles.append(cmd[idx + 1])
                    return 0, "https://example/pr/1\n", ""
            return real_runner(cmd, cwd=cwd)

        try:
            project_root = tmp_path / "project"
            project_root.mkdir()
            bundle = _bundle_with(
                [_file_candidate(fragment=fragment_name, project_root=project_root)],
                project_root=project_root,
            )
            with patch.object(emit_pr_module, "_run_subprocess", side_effect=fake_runner):
                report = emit_pr(
                    bundle,
                    forge_repo,
                    mode="github",
                    pr_title="Custom title for testing",
                    quiet=True,
                )
        finally:
            _unregister_fragment(fragment_name)

        assert observed_titles == ["Custom title for testing"]
        assert report.pr_url == "https://example/pr/1"


# ---------------------------------------------------------------------------
# Pre-condition failures
# ---------------------------------------------------------------------------


class TestEmitPrPreconditionFailures:
    def test_dirty_working_tree_errors_without_mutation(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        _init_forge_repo(forge_repo)
        # Add a dirty file post-init to fail the porcelain check.
        (forge_repo / "dirty.txt").write_text("oops", encoding="utf-8")

        project_root = tmp_path / "project"
        project_root.mkdir()
        fragment_name = "test_emit_dirty"
        _register_synthetic_fragment(fragment_name)
        try:
            bundle = _bundle_with(
                [_file_candidate(fragment=fragment_name, project_root=project_root)],
                project_root=project_root,
            )
            report = emit_pr(bundle, forge_repo, mode="branch", quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.errors, "expected pre-condition error"
        assert any("uncommitted" in err for err in report.errors)
        # Branch should NOT have been created.
        assert report.branch_name == ""
        # Confirm via git: still on whatever the initial branch was, no
        # ``harvest/*`` branch exists.
        result = subprocess.run(
            ["git", "branch", "--list", "harvest/*"],
            cwd=str(forge_repo),
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == ""

    def test_forge_repo_missing_dotgit_errors(self, tmp_path: Path) -> None:
        # Empty dir, no .git
        forge_repo = tmp_path / "not-a-repo"
        forge_repo.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()
        fragment_name = "test_emit_no_git"
        _register_synthetic_fragment(fragment_name)
        try:
            bundle = _bundle_with(
                [_file_candidate(fragment=fragment_name, project_root=project_root)],
                project_root=project_root,
            )
            report = emit_pr(bundle, forge_repo, mode="branch", quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.errors
        assert any("not a git working tree" in err for err in report.errors)
        assert report.branch_name == ""

    def test_forge_repo_does_not_exist(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "ghost-clone"  # never created
        project_root = tmp_path / "project"
        project_root.mkdir()
        fragment_name = "test_emit_ghost"
        _register_synthetic_fragment(fragment_name)
        try:
            bundle = _bundle_with(
                [_file_candidate(fragment=fragment_name, project_root=project_root)],
                project_root=project_root,
            )
            report = emit_pr(bundle, forge_repo, mode="branch", quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.errors
        assert any("does not exist" in err for err in report.errors)

    def test_github_mode_without_gh_installed_errors(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        _init_forge_repo(forge_repo)
        project_root = tmp_path / "project"
        project_root.mkdir()
        fragment_name = "test_emit_no_gh"
        _register_synthetic_fragment(fragment_name)

        real_runner = emit_pr_module._run_subprocess

        def fake_runner(cmd, *, cwd):  # type: ignore[no-untyped-def]
            if cmd and cmd[0] == "gh":
                # Simulate the FileNotFoundError exit path: rc=127.
                return 127, "", "gh: command not found"
            return real_runner(cmd, cwd=cwd)

        try:
            bundle = _bundle_with(
                [_file_candidate(fragment=fragment_name, project_root=project_root)],
                project_root=project_root,
            )
            with patch.object(emit_pr_module, "_run_subprocess", side_effect=fake_runner):
                report = emit_pr(bundle, forge_repo, mode="github", quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.errors
        assert any("gh" in err.lower() and "CLI" in err for err in report.errors)
        # No branch should have been created.
        assert report.branch_name == ""

    def test_github_mode_without_auth_errors(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        _init_forge_repo(forge_repo)
        project_root = tmp_path / "project"
        project_root.mkdir()
        fragment_name = "test_emit_no_auth"
        _register_synthetic_fragment(fragment_name)

        real_runner = emit_pr_module._run_subprocess

        def fake_runner(cmd, *, cwd):  # type: ignore[no-untyped-def]
            if cmd and cmd[0] == "gh":
                if cmd[1:3] == ["--version"]:
                    return 0, "gh version 2.40.0\n", ""
                if cmd[1:3] == ["auth", "status"]:
                    return 1, "", "You are not logged into any GitHub hosts."
            return real_runner(cmd, cwd=cwd)

        try:
            bundle = _bundle_with(
                [_file_candidate(fragment=fragment_name, project_root=project_root)],
                project_root=project_root,
            )
            with patch.object(emit_pr_module, "_run_subprocess", side_effect=fake_runner):
                report = emit_pr(bundle, forge_repo, mode="github", quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report.errors
        assert any("gh auth login" in err for err in report.errors)


# ---------------------------------------------------------------------------
# Risk filtering
# ---------------------------------------------------------------------------


class TestEmitPrRiskFilter:
    def test_needs_review_candidate_skipped_by_default(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        _init_forge_repo(forge_repo)
        fragment_name = "test_emit_risk_filter"
        _scaffold_synthetic_fragment_files(forge_repo)
        _register_synthetic_fragment(fragment_name)
        subprocess.run(["git", "add", "-A"], cwd=str(forge_repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "seed"], cwd=str(forge_repo), check=True, capture_output=True
        )
        try:
            project_root = tmp_path / "project"
            project_root.mkdir()
            bundle = _bundle_with(
                [
                    _file_candidate(
                        fragment=fragment_name,
                        project_root=project_root,
                        rel_path="src/app/main.py",
                        risk="needs-review",
                    )
                ],
                project_root=project_root,
            )
            report = emit_pr(bundle, forge_repo, mode="branch", quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert not report.errors
        assert report.committed == 0
        assert len(report.entries) == 1
        entry = report.entries[0]
        assert entry.action == "skipped-risk"
        assert "needs-review" in entry.reason

    def test_explicit_filter_admits_needs_review(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        _init_forge_repo(forge_repo)
        fragment_name = "test_emit_risk_admit"
        _scaffold_synthetic_fragment_files(forge_repo)
        _register_synthetic_fragment(fragment_name)
        subprocess.run(["git", "add", "-A"], cwd=str(forge_repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "seed"], cwd=str(forge_repo), check=True, capture_output=True
        )
        try:
            project_root = tmp_path / "project"
            project_root.mkdir()
            bundle = _bundle_with(
                [
                    _file_candidate(
                        fragment=fragment_name,
                        project_root=project_root,
                        rel_path="src/app/main.py",
                        risk="needs-review",
                    )
                ],
                project_root=project_root,
            )
            report = emit_pr(
                bundle,
                forge_repo,
                mode="branch",
                risk_filter=("safe-apply", "needs-review"),
                quiet=True,
            )
        finally:
            _unregister_fragment(fragment_name)

        assert not report.errors
        assert report.committed == 1


# ---------------------------------------------------------------------------
# Idempotency / re-run protection
# ---------------------------------------------------------------------------


class TestEmitPrIdempotency:
    def test_rerun_errors_branch_already_exists(self, tmp_path: Path) -> None:
        forge_repo = tmp_path / "forge-clone"
        _init_forge_repo(forge_repo)
        fragment_name = "test_emit_rerun"
        _scaffold_synthetic_fragment_files(forge_repo)
        _register_synthetic_fragment(fragment_name)
        subprocess.run(["git", "add", "-A"], cwd=str(forge_repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "seed"], cwd=str(forge_repo), check=True, capture_output=True
        )
        try:
            project_root = tmp_path / "project"
            project_root.mkdir()
            bundle = _bundle_with(
                [_file_candidate(fragment=fragment_name, project_root=project_root)],
                project_root=project_root,
            )
            report1 = emit_pr(bundle, forge_repo, mode="branch", quiet=True)
            assert not report1.errors
            assert report1.committed >= 1

            # Switch back to main so a second checkout -b on the same
            # branch name conflicts (rather than failing because we're
            # still on the harvest branch).
            subprocess.run(
                ["git", "checkout", "main"],
                cwd=str(forge_repo),
                check=True,
                capture_output=True,
            )
            report2 = emit_pr(bundle, forge_repo, mode="branch", quiet=True)
        finally:
            _unregister_fragment(fragment_name)

        assert report2.errors
        assert any("already exists" in err for err in report2.errors)


# ---------------------------------------------------------------------------
# CLI dispatch — end-to-end
# ---------------------------------------------------------------------------


def _emit_pr_namespace(
    *,
    project_path: str,
    harvest_out: str = ".forge-harvest",
    emit_pr: str = "branch",
    forge_repo: str | None = None,
    pr_title: str | None = None,
    pr_body: str | None = None,
    quiet: bool = True,
    json_output: bool = False,
    emit_pr_risk_filter: str | None = None,
) -> Namespace:
    return Namespace(
        project_path=project_path,
        harvest_out=harvest_out,
        harvest_scope=None,
        harvest_include="all",
        harvest_interactive=False,
        quiet=quiet,
        json_output=json_output,
        emit_pr=emit_pr,
        forge_repo=forge_repo,
        pr_title=pr_title,
        pr_body=pr_body,
        emit_pr_risk_filter=emit_pr_risk_filter,
    )


def _scaffold_minimal_project_for_harvest(tmp_path: Path) -> Path:
    """Build a project with one safe-apply block candidate available."""
    from forge.fragments import MARKER_PREFIX
    from forge.sync.manifest import write_forge_toml
    from forge.sync.merge import MergeBlockCollector, sha256_of_text

    project_root = tmp_path / "project"
    backend_dir = project_root / "services" / "api"
    src = backend_dir / "src" / "app"
    src.mkdir(parents=True)
    body = "# baseline body\n"
    edited = body + "# user added\n"
    feature_key = "middleware_cors"
    marker_bare = "MIDDLEWARE_REGISTRATION"
    block_text = (
        f"# {MARKER_PREFIX}BEGIN {feature_key}:{marker_bare}\n"
        f"{edited}"
        f"# {MARKER_PREFIX}END {feature_key}:{marker_bare}\n"
    )
    (src / "main.py").write_text(f"# top\n{block_text}# bottom\n")
    rel_path_in_project = "services/api/src/app/main.py"
    block_key = MergeBlockCollector.key_for(rel_path_in_project, feature_key, marker_bare)
    merge_blocks = {
        block_key: {
            "sha256": sha256_of_text(body),
            "fragment_name": feature_key,
            "fragment_version": "1.0.0",
        }
    }
    (backend_dir / "pyproject.toml").write_text('[project]\nname = "api"\nversion = "0.0.0"\n')
    write_forge_toml(
        project_root / "forge.toml",
        version="1.2.0",
        project_name="demo",
        templates={"python": "services/python-service-template"},
        options={},
        merge_blocks=merge_blocks,
    )
    return project_root


class TestEmitPrCLIDispatch:
    def test_cli_branch_mode_end_to_end(self, tmp_path: Path, capsys) -> None:
        """``forge --harvest --emit-pr=branch --forge-repo PATH`` writes
        a bundle, opens a harvest branch, and commits the candidate.

        We patch the underlying ``emit_pr`` call so we don't have to
        teach the test the full extractor pipeline (covered by
        tests/test_harvest.py). The CLI wiring assertions focus on
        argument parsing + dispatch.
        """
        project_root = _scaffold_minimal_project_for_harvest(tmp_path)
        forge_repo = tmp_path / "forge-clone"
        _init_forge_repo(forge_repo)

        called: dict[str, Any] = {}

        def fake_emit_pr(bundle, repo, *, mode, risk_filter, pr_title, pr_body, quiet):  # noqa: ARG001
            called["bundle"] = bundle
            called["repo"] = repo
            called["mode"] = mode
            called["risk_filter"] = risk_filter
            called["pr_title"] = pr_title
            return EmitPrReport(
                bundle_id=bundle.bundle_id,
                forge_repo=repo,
                branch_name=f"harvest/{bundle.bundle_id}",
                entries=(
                    EmitPrEntry(
                        fragment="middleware_cors",
                        kind="block",
                        commit_sha="deadbeefcafe",
                        files_touched=("inject.yaml",),
                        action="committed",
                    ),
                ),
            )

        ns = _emit_pr_namespace(
            project_path=str(project_root),
            harvest_out=str(tmp_path / "_harvest"),
            forge_repo=str(forge_repo),
            emit_pr="branch",
        )
        with patch(
            "forge.cli.commands.harvest.emit_pr",
            side_effect=fake_emit_pr,
        ):
            rc = _run_harvest(ns)
        assert rc == 0
        assert called["mode"] == "branch"
        assert called["repo"] == forge_repo.resolve()
        assert called["risk_filter"] == ("safe-apply",)
        # The bundle should still be materialised on disk.
        assert (tmp_path / "_harvest" / "manifest.json").is_file()
        # Human report rendered to stdout.
        out = capsys.readouterr().out
        assert "forge emit-pr" in out

    def test_cli_missing_forge_repo_exits_5(self, tmp_path: Path, capsys) -> None:
        project_root = _scaffold_minimal_project_for_harvest(tmp_path)
        ns = _emit_pr_namespace(
            project_path=str(project_root),
            harvest_out=str(tmp_path / "_harvest"),
            forge_repo=None,
            emit_pr="branch",
        )
        # Wipe $FORGE_REPO env var if set (test isolation).
        with patch.dict("os.environ", {}, clear=False):
            import os as _os

            _os.environ.pop("FORGE_REPO", None)
            rc = _run_harvest(ns)
        assert rc == 5
        err = capsys.readouterr().err
        assert "FORGE_REPO" in err or "forge-repo" in err

    def test_cli_picks_up_env_var(self, tmp_path: Path) -> None:
        project_root = _scaffold_minimal_project_for_harvest(tmp_path)
        forge_repo = tmp_path / "forge-clone-from-env"
        _init_forge_repo(forge_repo)

        called: dict[str, Any] = {}

        def fake_emit_pr(bundle, repo, **kwargs):  # noqa: ARG001
            called["repo"] = repo
            return EmitPrReport(
                bundle_id=bundle.bundle_id,
                forge_repo=repo,
                branch_name="harvest/test",
            )

        ns = _emit_pr_namespace(
            project_path=str(project_root),
            harvest_out=str(tmp_path / "_harvest"),
            forge_repo=None,  # not set via flag
            emit_pr="branch",
        )
        with (
            patch.dict("os.environ", {"FORGE_REPO": str(forge_repo)}),
            patch(
                "forge.cli.commands.harvest.emit_pr",
                side_effect=fake_emit_pr,
            ),
        ):
            rc = _run_harvest(ns)
        assert rc == 0
        assert called["repo"] == forge_repo.resolve()

    def test_cli_json_output_emits_emit_report_envelope(self, tmp_path: Path, capsys) -> None:
        project_root = _scaffold_minimal_project_for_harvest(tmp_path)
        forge_repo = tmp_path / "forge-clone"
        _init_forge_repo(forge_repo)

        def fake_emit_pr(bundle, repo, **kwargs):  # noqa: ARG001
            return EmitPrReport(
                bundle_id=bundle.bundle_id,
                forge_repo=repo,
                branch_name=f"harvest/{bundle.bundle_id}",
                entries=(
                    EmitPrEntry(
                        fragment="middleware_cors",
                        kind="block",
                        commit_sha="abc12345",
                        files_touched=("inject.yaml",),
                        action="committed",
                    ),
                ),
                pr_url="",
            )

        ns = _emit_pr_namespace(
            project_path=str(project_root),
            harvest_out=str(tmp_path / "_harvest"),
            forge_repo=str(forge_repo),
            emit_pr="branch",
            json_output=True,
        )
        with patch(
            "forge.cli.commands.harvest.emit_pr",
            side_effect=fake_emit_pr,
        ):
            rc = _run_harvest(ns)
        assert rc == 0
        out = capsys.readouterr().out.strip()
        envelope = json.loads(out)
        assert envelope["bundle_id"]
        assert envelope["branch_name"].startswith("harvest/")
        assert envelope["committed"] == 1
        assert isinstance(envelope["entries"], list)
        assert envelope["entries"][0]["action"] == "committed"

    def test_cli_emit_pr_off_skips_emit_step(self, tmp_path: Path) -> None:
        """Default --emit-pr=off keeps the harvest-only behaviour intact."""
        project_root = _scaffold_minimal_project_for_harvest(tmp_path)

        called = {"count": 0}

        def fake_emit_pr(*args, **kwargs):  # noqa: ARG001
            called["count"] += 1
            return EmitPrReport(
                bundle_id="x",
                forge_repo=Path("."),
                branch_name="",
            )

        ns = _emit_pr_namespace(
            project_path=str(project_root),
            harvest_out=str(tmp_path / "_harvest"),
            forge_repo=None,
            emit_pr="off",
        )
        with patch("forge.cli.commands.harvest.emit_pr", side_effect=fake_emit_pr):
            rc = _run_harvest(ns)
        assert rc == 0
        assert called["count"] == 0

    def test_cli_emit_pr_pre_condition_failure_returns_5(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        """A dirty forge_repo surfaces via emit_pr's report.errors[] →
        CLI exits 5."""
        project_root = _scaffold_minimal_project_for_harvest(tmp_path)
        forge_repo = tmp_path / "forge-clone"
        _init_forge_repo(forge_repo)
        # Make it dirty.
        (forge_repo / "untracked.txt").write_text("dirt", encoding="utf-8")

        ns = _emit_pr_namespace(
            project_path=str(project_root),
            harvest_out=str(tmp_path / "_harvest"),
            forge_repo=str(forge_repo),
            emit_pr="branch",
        )
        # No patch — let the real emit_pr run, since it's a
        # pre-condition path that won't try to apply anything.
        rc = _run_harvest(ns)
        assert rc == 5
        out = capsys.readouterr().out
        # Human render writes the error to stdout.
        assert "uncommitted" in out or "pre-condition error" in out


# ---------------------------------------------------------------------------
# Report rendering / JSON shape
# ---------------------------------------------------------------------------


class TestEmitPrReportRendering:
    def test_to_dict_round_trips_through_json(self, tmp_path: Path) -> None:
        report = EmitPrReport(
            bundle_id="harvest-abc",
            forge_repo=tmp_path / "forge",
            branch_name="harvest/harvest-abc",
            entries=(
                EmitPrEntry(
                    fragment="middleware_cors",
                    kind="block",
                    commit_sha="deadbeef",
                    files_touched=("inject.yaml",),
                    action="committed",
                ),
                EmitPrEntry(
                    fragment="other",
                    kind="files",
                    commit_sha=None,
                    files_touched=(),
                    action="deferred",
                    reason="non-literal tuple",
                ),
            ),
            pr_url="https://github.com/x/y/pull/1",
        )
        envelope = report.to_dict()
        # Round-trip through JSON to make sure the shape is serializable.
        re_decoded = json.loads(json.dumps(envelope))
        assert re_decoded["committed"] == 1
        assert re_decoded["deferred"] == 1
        assert re_decoded["pr_url"] == "https://github.com/x/y/pull/1"
        assert re_decoded["entries"][0]["commit_sha"] == "deadbeef"
        assert re_decoded["entries"][1]["reason"] == "non-literal tuple"

    def test_render_human_branch_level_error_short_circuits(self, tmp_path: Path) -> None:
        import io

        buf = io.StringIO()
        report = EmitPrReport(
            bundle_id="x",
            forge_repo=tmp_path,
            branch_name="",
            entries=(),
            errors=("forge_repo not a git working tree",),
        )
        report.render_human(buf)
        out = buf.getvalue()
        assert "pre-condition error" in out
        assert "forge_repo not a git working tree" in out

    def test_render_human_lists_committed_entries(self, tmp_path: Path) -> None:
        import io

        buf = io.StringIO()
        report = EmitPrReport(
            bundle_id="harvest-xyz",
            forge_repo=tmp_path,
            branch_name="harvest/xyz",
            entries=(
                EmitPrEntry(
                    fragment="middleware_cors",
                    kind="block",
                    commit_sha="abcd1234ef56",
                    files_touched=("inject.yaml",),
                    action="committed",
                ),
            ),
        )
        report.render_human(buf)
        out = buf.getvalue()
        assert "committed=1" in out
        assert "harvest/xyz" in out
        assert "middleware_cors/block" in out


# ---------------------------------------------------------------------------
# Default PR title / body
# ---------------------------------------------------------------------------


class TestEmitPrDefaultMessages:
    def test_default_title_uses_project_name_and_fragments(self, tmp_path: Path) -> None:
        from forge.sync.project_to_forge.emit_pr import _default_pr_title

        bundle = _bundle_with([], project_root=tmp_path / "my-project")
        entries = (
            EmitPrEntry(
                fragment="middleware_cors",
                kind="block",
                commit_sha="abc",
                files_touched=(),
                action="committed",
            ),
            EmitPrEntry(
                fragment="rate_limit",
                kind="files",
                commit_sha="def",
                files_touched=(),
                action="committed",
            ),
        )
        title = _default_pr_title(bundle, entries)
        assert "my-project" in title
        assert "middleware_cors" in title
        assert "rate_limit" in title

    def test_default_body_includes_bundle_metadata(self, tmp_path: Path) -> None:
        from forge.sync.project_to_forge.emit_pr import _default_pr_body

        bundle = HarvestBundle(
            bundle_id="harvest-test-123",
            project_root=tmp_path / "demo-project",
            forge_version="1.2.0-test",
            candidates=[
                CandidatePatch(
                    fragment="middleware_cors",
                    backend="api",
                    kind="block",
                    rel_path="src/app/main.py",
                    target_path="",
                    diff="",
                    baseline_sha=None,
                    current_sha="",
                    risk="safe-apply",
                )
            ],
        )
        entries = (
            EmitPrEntry(
                fragment="middleware_cors",
                kind="block",
                commit_sha="abc",
                files_touched=("inject.yaml",),
                action="committed",
            ),
        )
        body = _default_pr_body(bundle, entries)
        assert "harvest-test-123" in body
        assert "1.2.0-test" in body
        assert "demo-project" in body or "demo" in body
        assert "Reviewer checklist" in body
        assert "round-trip.md" in body
