"""Tests for ``--harvest-interactive`` (Theme 2C).

Covers the per-candidate prompt loop wired into
:func:`forge.sync.project_to_forge.harvester.harvest_project`:

* deterministic accept/skip decisions prune the bundle correctly,
* ``quit`` short-circuits with :class:`HarvestAborted` and writes no
  bundle on disk,
* the headless default path (``interactive=False``) is byte-equal to
  the legacy non-prompted behaviour (no prompt callback invoked),
* the CLI dispatcher catches ``HarvestAborted`` and surfaces it as
  exit code 130 with no bundle directory materialised,
* the in-line ``_short_diff_stat`` / ``_format_candidate_header``
  helpers render the expected ``+N -M`` summary so the UI doesn't
  drift away from the test-fixture diffs we ship in
  :mod:`tests.test_harvest`.
"""

from __future__ import annotations

import json
from argparse import Namespace
from collections import deque
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from forge.cli.commands.harvest import _run_harvest
from forge.cli.interactive import (
    _format_candidate_header,
    _short_diff_stat,
    prompt_harvest_candidate,
)
from forge.extractors.pipeline import CandidatePatch
from forge.fragments import MARKER_PREFIX
from forge.sync.manifest import write_forge_toml
from forge.sync.merge import MergeBlockCollector, sha256_of_text
from forge.sync.project_to_forge.harvester import (
    HarvestAborted,
    _run_interactive_review,
    harvest_project,
)

# ---------------------------------------------------------------------------
# Fixture helpers — mirror the inline scaffold in ``tests/test_harvest.py``.
# We duplicate the helpers (rather than importing) so this file stays
# coherent if test_harvest's private helpers move.
# ---------------------------------------------------------------------------


def _block_text(feature_key: str, marker_bare: str, body: str) -> str:
    return (
        f"# {MARKER_PREFIX}BEGIN {feature_key}:{marker_bare}\n"
        f"{body}"
        f"# {MARKER_PREFIX}END {feature_key}:{marker_bare}\n"
    )


def _scaffold_project(
    tmp_path: Path,
    *,
    body: str = "# block body line 1\n# block body line 2\n",
    backend_name: str = "api",
) -> dict[str, Any]:
    backend_dir = tmp_path / "services" / backend_name
    src = backend_dir / "src" / "app"
    src.mkdir(parents=True)
    main_py = src / "main.py"
    block_segment = _block_text("middleware_cors", "MIDDLEWARE_REGISTRATION", body)
    main_py.write_text(f"# top\n{block_segment}# bottom\n")

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
    (backend_dir / "pyproject.toml").write_text(
        '[project]\nname = "api"\nversion = "0.0.0"\n'
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


def _edit_block(meta: dict[str, Any], new_body: str) -> None:
    """Replace the block body in the scaffolded project's main.py."""
    original_block = _block_text(
        "middleware_cors", "MIDDLEWARE_REGISTRATION", meta["block_body"]
    )
    new_block = _block_text("middleware_cors", "MIDDLEWARE_REGISTRATION", new_body)
    meta["main_py"].write_text(
        meta["main_py"].read_text().replace(original_block, new_block)
    )


def _make_candidate(**overrides: Any) -> CandidatePatch:
    """Build a minimal CandidatePatch for unit-testing the review loop."""
    defaults: dict[str, Any] = {
        "fragment": "middleware_cors",
        "backend": "api",
        "kind": "block",
        "rel_path": "src/app/main.py",
        "target_path": "/tmp/proj/services/api/src/app/main.py",
        "diff": "--- a/x\n+++ b/x\n@@ -1 +1,2 @@\n line\n+new\n",
        "baseline_sha": "abc",
        "current_sha": "def",
        "risk": "safe-apply",
        "rationale": "test",
    }
    defaults.update(overrides)
    return CandidatePatch(**defaults)


# ---------------------------------------------------------------------------
# Unit-level: the prompt loop and its helpers
# ---------------------------------------------------------------------------


class TestRunInteractiveReview:
    def test_accept_all_keeps_every_candidate(self) -> None:
        cands = [_make_candidate(rel_path=f"f{i}.py") for i in range(3)]
        prompt = MagicMock(return_value="accept")
        out = _run_interactive_review(cands, prompt)
        assert out == cands
        assert prompt.call_count == 3
        # Each call should receive (cand, 1-indexed-pos, total).
        for n, call in enumerate(prompt.call_args_list, start=1):
            args, _ = call
            assert args[1] == n
            assert args[2] == 3

    def test_skip_drops_only_skipped(self) -> None:
        cands = [_make_candidate(rel_path=f"f{i}.py") for i in range(4)]
        decisions = deque(["accept", "skip", "accept", "skip"])
        prompt = lambda c, i, t: decisions.popleft()  # noqa: E731
        out = _run_interactive_review(cands, prompt)
        assert [c.rel_path for c in out] == ["f0.py", "f2.py"]

    def test_quit_raises_harvest_aborted(self) -> None:
        cands = [_make_candidate(rel_path=f"f{i}.py") for i in range(5)]
        decisions = deque(["accept", "accept", "quit"])
        prompt = lambda c, i, t: decisions.popleft()  # noqa: E731
        with pytest.raises(HarvestAborted) as ei:
            _run_interactive_review(cands, prompt)
        # ``inspected_count`` records 1-indexed position of the quit
        # decision so an operator can see "I quit at candidate 3 of 5".
        assert ei.value.inspected_count == 3

    def test_unknown_decision_treated_as_skip(self) -> None:
        # Defensive contract — a buggy callback returning gibberish
        # shouldn't crash the review pass mid-way through.
        cands = [_make_candidate(rel_path="a.py"), _make_candidate(rel_path="b.py")]
        decisions = deque(["bogus", "accept"])
        prompt = lambda c, i, t: decisions.popleft()  # noqa: E731
        out = _run_interactive_review(cands, prompt)
        assert [c.rel_path for c in out] == ["b.py"]


class TestShortDiffStat:
    def test_counts_data_lines_only(self) -> None:
        diff = (
            "--- a/x\n"
            "+++ b/x\n"
            "@@ -1,3 +1,4 @@\n"
            " context\n"
            "-removed\n"
            "+added one\n"
            "+added two\n"
        )
        # Header lines (---/+++) are excluded; @@ hunk markers don't
        # start with +/- so they're naturally ignored.
        assert _short_diff_stat(diff) == "+2 -1"

    def test_empty_diff(self) -> None:
        assert _short_diff_stat("") == "(no diff)"


class TestFormatCandidateHeader:
    def test_includes_kind_and_diff_stat(self) -> None:
        cand = _make_candidate(kind="block", risk="safe-apply")
        header = _format_candidate_header(cand, index=2, total=7)
        assert "Candidate 2 of 7" in header
        assert "Kind:     block" in header
        assert "risk: safe-apply" in header
        # Diff stat reflects the one + line in the fixture diff.
        assert "+1 -0" in header

    def test_truncates_long_diffs(self) -> None:
        long_diff_body = "\n".join(f"+line {n}" for n in range(50))
        long_diff = (
            "--- a/x\n+++ b/x\n@@ -1 +1,50 @@\n" + long_diff_body + "\n"
        )
        cand = _make_candidate(diff=long_diff)
        header = _format_candidate_header(cand, index=1, total=1)
        # 50 added lines minus the 12-line preview => "more line(s)"
        # marker pinned to the surrounding text so future preview-cap
        # tweaks don't silently change the contract.
        assert "more line(s) — choose 'view full diff'" in header


# ---------------------------------------------------------------------------
# Integration: harvest_project with a prompt_callback injected
# ---------------------------------------------------------------------------


class TestHarvestProjectInteractive:
    def test_accept_all_matches_non_interactive_bundle(self, tmp_path: Path) -> None:
        # Edit the block so a real candidate is emitted.
        meta = _scaffold_project(tmp_path)
        _edit_block(meta, meta["block_body"] + "# new\n")

        bundle_off = harvest_project(tmp_path, quiet=True)
        bundle_on = harvest_project(
            tmp_path,
            quiet=True,
            interactive=True,
            prompt_callback=lambda *_: "accept",
        )
        # Bundle ids differ by timestamp; what we care about is that
        # the candidate sets match.
        assert [c.rel_path for c in bundle_off.candidates] == [
            c.rel_path for c in bundle_on.candidates
        ]

    def test_skip_prunes_candidate_from_bundle(self, tmp_path: Path) -> None:
        meta = _scaffold_project(tmp_path)
        _edit_block(meta, meta["block_body"] + "# new\n")

        bundle = harvest_project(
            tmp_path,
            quiet=True,
            interactive=True,
            prompt_callback=lambda *_: "skip",
        )
        # Skipping the only real candidate also drops its cross-lang
        # suggestions (a non-tier-1 fragment in this fixture wouldn't
        # generate any anyway, but the contract holds regardless).
        assert bundle.candidates == []

    def test_quit_raises_and_writes_no_bundle(self, tmp_path: Path) -> None:
        meta = _scaffold_project(tmp_path)
        _edit_block(meta, meta["block_body"] + "# new\n")

        out_dir = tmp_path / "_harvest_quit"
        with pytest.raises(HarvestAborted):
            harvest_project(
                tmp_path,
                out_dir=out_dir,
                quiet=True,
                interactive=True,
                prompt_callback=lambda *_: "quit",
            )
        # The bundle directory must NOT have been materialised — quit is
        # an "abort, no partial output" contract.
        assert not out_dir.exists()

    def test_interactive_false_ignores_prompt_callback(self, tmp_path: Path) -> None:
        # Passing prompt_callback without interactive=True is a no-op;
        # we use a callback that would raise to prove it never fires.
        meta = _scaffold_project(tmp_path)
        _edit_block(meta, meta["block_body"] + "# new\n")

        prompt = MagicMock(side_effect=AssertionError("must not run"))
        bundle = harvest_project(
            tmp_path,
            quiet=True,
            interactive=False,
            prompt_callback=prompt,
        )
        assert prompt.call_count == 0
        assert bundle.candidates  # default headless path kept candidate(s)

    def test_interactive_true_no_callback_keeps_everything(
        self, tmp_path: Path
    ) -> None:
        # Belt-and-braces: ``interactive=True`` without a callback
        # falls through to "accept all" rather than crashing on a None
        # call. Mirrors the CLI's defensive ``if interactive:`` guard.
        meta = _scaffold_project(tmp_path)
        _edit_block(meta, meta["block_body"] + "# new\n")
        bundle = harvest_project(
            tmp_path,
            quiet=True,
            interactive=True,
            prompt_callback=None,
        )
        assert bundle.candidates


# ---------------------------------------------------------------------------
# CLI dispatcher: --harvest-interactive end-to-end
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


class TestHarvestCLIInteractive:
    def test_cli_quit_returns_130_and_writes_no_bundle(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        meta = _scaffold_project(tmp_path)
        _edit_block(meta, meta["block_body"] + "# new\n")

        # Replace the real questionary prompt with a stub that selects
        # "quit" on the first call — we don't want to drive a TTY here.
        import forge.cli.interactive as interactive_mod  # noqa: PLC0415

        monkeypatch.setattr(
            interactive_mod,
            "prompt_harvest_candidate",
            lambda cand, i, t: "quit",
        )

        out_dir = tmp_path / "_harvest_cli_quit"
        ns = _harvest_namespace(
            project_path=str(tmp_path),
            harvest_out=str(out_dir),
            harvest_interactive=True,
        )
        rc = _run_harvest(ns)
        assert rc == 130
        assert not out_dir.exists()
        err = capsys.readouterr().err
        assert "aborted by operator" in err

    def test_cli_accept_writes_bundle(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        meta = _scaffold_project(tmp_path)
        _edit_block(meta, meta["block_body"] + "# new\n")

        import forge.cli.interactive as interactive_mod  # noqa: PLC0415

        monkeypatch.setattr(
            interactive_mod,
            "prompt_harvest_candidate",
            lambda cand, i, t: "accept",
        )

        out_dir = tmp_path / "_harvest_cli_accept"
        ns = _harvest_namespace(
            project_path=str(tmp_path),
            harvest_out=str(out_dir),
            harvest_interactive=True,
        )
        rc = _run_harvest(ns)
        assert rc == 0
        assert (out_dir / "manifest.json").is_file()
        envelope = json.loads((out_dir / "manifest.json").read_text())
        assert envelope["candidates"]

    def test_cli_skip_writes_empty_bundle(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        meta = _scaffold_project(tmp_path)
        _edit_block(meta, meta["block_body"] + "# new\n")

        import forge.cli.interactive as interactive_mod  # noqa: PLC0415

        monkeypatch.setattr(
            interactive_mod,
            "prompt_harvest_candidate",
            lambda cand, i, t: "skip",
        )

        out_dir = tmp_path / "_harvest_cli_skip"
        ns = _harvest_namespace(
            project_path=str(tmp_path),
            harvest_out=str(out_dir),
            harvest_interactive=True,
        )
        rc = _run_harvest(ns)
        assert rc == 0
        envelope = json.loads((out_dir / "manifest.json").read_text())
        assert envelope["candidates"] == []

    def test_cli_quit_json_mode_emits_aborted_envelope(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        meta = _scaffold_project(tmp_path)
        _edit_block(meta, meta["block_body"] + "# new\n")

        import forge.cli.interactive as interactive_mod  # noqa: PLC0415

        monkeypatch.setattr(
            interactive_mod,
            "prompt_harvest_candidate",
            lambda cand, i, t: "quit",
        )

        ns = _harvest_namespace(
            project_path=str(tmp_path),
            harvest_out="-",  # streaming JSON mode
            harvest_interactive=True,
        )
        rc = _run_harvest(ns)
        assert rc == 130
        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["aborted"] is True
        assert envelope["inspected_count"] >= 1


# ---------------------------------------------------------------------------
# prompt_harvest_candidate — verify the questionary integration shape.
# We patch the questionary.select call so we don't open a real TTY.
# ---------------------------------------------------------------------------


class TestPromptHarvestCandidate:
    def test_view_full_diff_then_accept(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # First call returns "view full diff" → prompt should re-ask;
        # second call returns "accept" → prompt should return "accept".
        responses = deque(["view full diff", "accept"])

        class _StubSelect:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def ask(self) -> str:
                return responses.popleft()

        import forge.cli.interactive as interactive_mod  # noqa: PLC0415

        monkeypatch.setattr(interactive_mod.questionary, "select", _StubSelect)

        cand = _make_candidate(
            diff="--- a/x\n+++ b/x\n@@ -1 +1,2 @@\n a\n+b\n c\n",
        )
        decision = prompt_harvest_candidate(cand, index=1, total=1)
        assert decision == "accept"
        # The full-diff branch must have echoed the diff to stdout.
        out = capsys.readouterr().out
        assert "Full diff for" in out

    def test_ctrl_c_returns_quit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _NullSelect:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def ask(self) -> None:
                return None  # questionary returns None on Ctrl-C / EOF.

        import forge.cli.interactive as interactive_mod  # noqa: PLC0415

        monkeypatch.setattr(interactive_mod.questionary, "select", _NullSelect)

        decision = prompt_harvest_candidate(_make_candidate(), index=1, total=1)
        assert decision == "quit"
