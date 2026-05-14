"""Round-trip invariants for the bidirectional-sync cycle (Phase 5/6).

This module codifies the three load-bearing invariants of the
forge → project → forge cycle as automated tests:

* **FR1 — fresh-generate-has-nothing-to-harvest (block + files):**
  Immediately after :func:`forge.generator.generate` emits a project,
  :func:`forge.sync.project_to_forge.harvest_project` MUST find zero
  ``"block"`` and zero ``"files"`` candidates. ``deps`` and ``env``
  extractors legitimately surface base-template dependencies the
  fragments don't claim (e.g. ``aiosqlite``, ``alembic``), so the
  strict-zero check is scoped to the kinds the apply-back path
  actually supports.

* **FR2 — forward-then-reverse round-trip:**
  Generate → edit a literal block in place → harvest → apply the
  bundle to the LIVE forge tree (snapshotted + reverted in
  ``finally``) → regenerate. The second generate MUST byte-equal the
  first generate plus the user's edit (modulo emitted_at timestamps,
  sentinel fingerprints, derived sha256 fields in forge.toml, .git/
  and .copier-answers.yml — see ``_diff_project_trees`` for the
  exclusion contract).

* **RF1 — reverse-then-forward promotes edits to baseline:**
  Generate → edit → harvest → apply to fragments → ``update_project``.
  After re-application, the project's provenance state MUST classify
  every block-mediated file as ``unchanged`` (the user edit is now
  part of the baseline). ``.env.example`` / ``pyproject.toml`` are
  excluded from the assertion because they classify as
  ``user-modified`` even on a fresh generate (deps/env appliers
  append after the manifest stamp — a separate infrastructure issue).

Phase 6 wires the block apply-back surface
(:func:`apply_bundle_to_fragments` rewrites inject.yaml ``snippet:``
entries from :attr:`CandidatePatch.current_body`), so FR2 and RF1
now run as real assertions. See :doc:`docs/round-trip.md` for the
formal statements.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# Scenarios FR1 runs against under the ``e2e`` marker. Picked for
# diversity — each backend language and each frontend framework is
# represented at least once across the three. These are slow
# (~30-180s/scenario, especially node_vue_full + rust_svelte_min)
# so they're gated behind ``e2e`` and run nightly via matrix lane D
# in addition to the e2e marker.
_FR1_SCENARIOS_E2E: tuple[str, ...] = (
    "node_vue_full",
    "rust_svelte_min",
)

# The fast scenario carries FR1 on every PR. ``py_only_headless`` is
# the lightest configuration in the matrix (no frontend; ~8-10s end-
# to-end) so it can sit in the default test surface without bloating
# wall-clock.
_FR1_FAST_SCENARIO: str = "py_only_headless"


def _build_project(scenario_name: str, tmp_path: Path) -> Path:
    """Generate ``scenario_name`` into ``tmp_path`` and return the project root.

    Delegates to the matrix runner's scenario loader so this test file
    stays in sync with the matrix lane definitions without duplicating
    config-builder boilerplate.
    """
    # Lazy imports — these pull a lot of forge surface, so we only
    # take the cost in the tests that actually generate.
    from forge.generator import generate  # noqa: PLC0415
    from tests.matrix.runner import _project_config_from_dict, load_scenarios  # noqa: PLC0415

    scenarios = load_scenarios()
    scenario = next((s for s in scenarios if s.name == scenario_name), None)
    if scenario is None:
        pytest.fail(f"scenario {scenario_name!r} not defined in tests/matrix/scenarios.yaml")
    cfg_copy = dict(scenario.config)
    cfg_copy["output_dir"] = str(tmp_path)
    project_config = _project_config_from_dict(cfg_copy)
    project_config.validate()
    return generate(project_config, quiet=True, dry_run=False)


# ---------------------------------------------------------------------------
# FR1 — fresh-generate has nothing to harvest (block + files kinds)
# ---------------------------------------------------------------------------


def _assert_fr1(scenario_name: str, tmp_path: Path) -> None:
    """Shared FR1 assertion used by both the fast and e2e variants.

    Generates ``scenario_name`` into ``tmp_path``, runs the harvester,
    and asserts zero ``"block"`` / ``"files"`` candidates were
    produced. The scope-to-block-and-files restriction is intentional —
    the deps / env extractors legitimately surface base-template
    dependencies that no fragment owns (see
    :class:`forge.extractors.deps.DepsExtractor` for the reasoning).
    """
    from forge.sync.project_to_forge import harvest_project  # noqa: PLC0415

    project_root = _build_project(scenario_name, tmp_path)
    bundle = harvest_project(project_root, quiet=True)

    block_or_files = [c for c in bundle.candidates if c.kind in ("block", "files")]
    if block_or_files:
        # Surface the first few for diagnosis. The full list often
        # signals one root cause (e.g. a fragment whose inject.yaml
        # snippet doesn't round-trip cleanly via _render_snippet)
        # repeated across N targets.
        diag = "\n".join(
            f"  {c.kind} {c.risk} {c.fragment} {c.rel_path}: {c.rationale[:120]}"
            for c in block_or_files[:10]
        )
        more = f"\n  ... and {len(block_or_files) - 10} more" if len(block_or_files) > 10 else ""
        pytest.fail(
            f"FR1 violation on scenario {scenario_name!r}: "
            f"fresh-generate produced {len(block_or_files)} block/files "
            f"candidate(s):\n{diag}{more}"
        )


def test_fr1_fresh_generate_has_no_block_or_files_candidates_fast(
    tmp_path: Path,
) -> None:
    """FR1 against the fastest scenario — runs on every PR.

    The headline round-trip invariant: if the user hasn't touched
    anything, the harvester sees nothing to back-port. ``py_only_headless``
    is the lightest matrix scenario (~8s generate + harvest on a CI
    runner) and carries the FR1 signal in the default test surface so
    a regression surfaces immediately on the PR that introduces it.

    The broader 3-scenario sweep lives under ``e2e`` (see
    :func:`test_fr1_fresh_generate_has_no_block_or_files_candidates_e2e`)
    and runs nightly via matrix lane D.
    """
    _assert_fr1(_FR1_FAST_SCENARIO, tmp_path)


@pytest.mark.e2e
@pytest.mark.parametrize("scenario_name", _FR1_SCENARIOS_E2E)
def test_fr1_fresh_generate_has_no_block_or_files_candidates_e2e(
    scenario_name: str,
    tmp_path: Path,
) -> None:
    """FR1 across the slower scenarios (Node/Vue + Rust/Svelte).

    Carries the FR1 contract on cross-stack configurations. Slow
    (~3-5 min per scenario on Windows; ~1 min on Linux CI) so it's
    gated behind the ``e2e`` marker and runs only on opt-in test
    invocations plus the nightly matrix lane D.
    """
    _assert_fr1(scenario_name, tmp_path)


# ---------------------------------------------------------------------------
# FR2 — forward-then-reverse round-trip
# ---------------------------------------------------------------------------
#
# FR2 asserts: forward-generate → edit a block → harvest → apply the
# bundle to the fragment tree → regenerate. The second regenerate must
# byte-equal the first generate-after-edit (modulo documented noise:
# emitted_at timestamps and FORGE sentinel fingerprints — see
# ``_normalize_project_tree`` for the exclusion contract).
#
# Phase 6 wired the block apply-back path (``apply_bundle_to_fragments``
# rewrites inject.yaml ``snippet:`` entries from ``CandidatePatch.current_body``),
# so FR2 now runs as a real assertion rather than an ``xfail``.


@pytest.mark.e2e
@pytest.mark.parametrize("scenario_name", ("py_only_headless",))
def test_fr2_forward_then_reverse_round_trip(
    scenario_name: str,
    tmp_path: Path,
) -> None:
    """Generate → edit → harvest → apply → regenerate. Output must match.

    The edit targets a literal-text (non-Jinja) sentinel block: the
    apply-back literalizes the user's body into the fragment's
    ``inject.yaml`` ``snippet:`` field, so the post-cycle regenerate
    must re-emit the same body. Jinja-interpolated blocks would
    converge to a different rendered text on the second pass — those
    are filtered to ``needs-review`` at harvest, so they wouldn't
    apply under the default ``safe-apply`` risk filter anyway, but we
    explicitly pick a literal block to keep the test crisp.

    Apply-back mutates the LIVE forge tree (snapshotted + reverted in
    ``finally``) because the generator's fragment registry is a
    process-wide singleton — applying to a clone would have no effect
    on the second ``generate()`` call.
    """
    from forge.sync.project_to_forge import (  # noqa: PLC0415
        apply_bundle_to_fragments,
        harvest_project,
    )

    project_a = tmp_path / "project-a"
    project_a.mkdir()
    project_root_a = _build_project(scenario_name, project_a)

    edited_target, edit_meta = _edit_a_known_literal_block(project_root_a)
    if edited_target is None:
        pytest.skip("scenario emitted no editable literal block — FR2 needs one to harvest")

    bundle = harvest_project(project_root_a, quiet=True)

    # Filter to block candidates only — the deps/env candidates
    # legitimately surface base-template drift that apply-back can't
    # auto-resolve (Phase 7+). Block-only keeps the test focused on
    # FR2's contract.
    bundle.candidates[:] = [c for c in bundle.candidates if c.kind == "block"]
    if not any(c.risk == "safe-apply" for c in bundle.candidates):
        pytest.skip(
            "no safe-apply block candidates after edit — fragment must be Jinja-"
            "rendered or the edit landed on a needs-review path"
        )

    # Snapshot every inject.yaml the apply-back might rewrite, then
    # restore them on the way out so the live forge tree stays pristine.
    with _live_forge_apply_back_guard():
        report = apply_bundle_to_fragments(bundle, _live_forge_root(), quiet=True)
        assert report.errored == 0, (
            f"apply-back errored on {report.errored} candidate(s); "
            f"first error: {next((e.error for e in report.entries if e.status == 'errored'), '')}"
        )

        project_b = tmp_path / "project-b"
        project_b.mkdir()
        project_root_b = _build_project(scenario_name, project_b)

        differing = _diff_project_trees(project_root_a, project_root_b)
        assert differing == [], (
            "FR2 round-trip failed: regenerated project does not match the edited "
            f"project. Edit was {edit_meta!r}. Differing files (first 10): "
            f"{differing[:10]}"
        )


# ---------------------------------------------------------------------------
# RF1 — reverse-then-forward promotes edits to baseline
# ---------------------------------------------------------------------------
#
# Phase 6 enables RF1 to pass alongside FR2: the apply-back step now
# writes the user's edits into the fragment source, so the subsequent
# ``update_project`` re-stamps the baseline SHA with the user's body.


@pytest.mark.e2e
@pytest.mark.parametrize("scenario_name", ("py_only_headless",))
def test_rf1_reverse_then_forward_promotes_edits_to_baseline(
    scenario_name: str,
    tmp_path: Path,
) -> None:
    """After apply-back + update, the user's edits are part of the baseline.

    Generate → edit → harvest → apply to fragments → ``update_project``.
    The post-update :func:`classify_project_state` MUST report zero
    user-modified files: the harvest cycle promoted the user's text
    into the fragment baseline, so the recorded SHA now matches what's
    on disk.

    Same live-forge-tree pattern as FR2: snapshot affected inject.yaml
    files, apply, run update_project, classify, and restore the
    snapshot in ``finally``.
    """
    from forge.sync.forge_to_project import (  # noqa: PLC0415
        classify_project_state,
        update_project,
    )
    from forge.sync.manifest import read_forge_toml  # noqa: PLC0415
    from forge.sync.project_to_forge import (  # noqa: PLC0415
        apply_bundle_to_fragments,
        harvest_project,
    )

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    project_root = _build_project(scenario_name, project_dir)

    edited_target, edit_meta = _edit_a_known_literal_block(project_root)
    if edited_target is None:
        pytest.skip("scenario emitted no editable literal block — RF1 needs one")

    bundle = harvest_project(project_root, quiet=True)
    bundle.candidates[:] = [c for c in bundle.candidates if c.kind == "block"]
    if not any(c.risk == "safe-apply" for c in bundle.candidates):
        pytest.skip("no safe-apply block candidates after edit")

    with _live_forge_apply_back_guard():
        report = apply_bundle_to_fragments(bundle, _live_forge_root(), quiet=True)
        assert report.errored == 0, (
            f"apply-back errored on {report.errored} candidate(s); "
            f"first error: {next((e.error for e in report.entries if e.status == 'errored'), '')}"
        )

        update_project(project_root, quiet=True)

        data = read_forge_toml(project_root / "forge.toml")
        classification = classify_project_state(project_root, data.provenance)
        # Filter the known pre-existing append-after-stamp drift on the
        # files that the deps/env appliers mutate AFTER provenance is
        # recorded (``.env.example``, ``pyproject.toml`` /
        # ``package.json`` / ``Cargo.toml``). A fresh ``generate()``
        # already classifies these as ``user-modified`` because the
        # appliers append fragment deps/env after the manifest is
        # stamped; restamping that infrastructure is a separate fix
        # (tracked outside this PR). RF1 here scopes to BLOCK-mediated
        # files — the harvest-cycle's actual contract.
        user_modified = [
            p
            for p, s in classification.items()
            if s == "user-modified" and not _is_pre_existing_drift(p)
        ]
        assert user_modified == [], (
            f"RF1 violation: post-cycle classification still reports "
            f"user-modified files: {user_modified[:5]}. Edit was {edit_meta!r}."
        )


# ---------------------------------------------------------------------------
# Helpers (used by FR2 / RF1; FR1 doesn't need them)
# ---------------------------------------------------------------------------


def _clone_forge_source(dst: Path) -> None:
    """Mirror the live forge source tree into ``dst``.

    Retained for callers that want a fragment-tree clone for apply-back
    in isolation (the inverse-test fixtures and the matrix runner). FR2
    / RF1 don't use this any more — see :func:`_live_forge_apply_back_guard`
    for the snapshot+restore pattern.
    """
    import shutil  # noqa: PLC0415

    repo_root = Path(__file__).resolve().parent.parent
    dst.mkdir(parents=True, exist_ok=True)
    for sub in ("forge",):
        src_dir = repo_root / sub
        if src_dir.is_dir():
            shutil.copytree(str(src_dir), str(dst / sub))


def _live_forge_root() -> Path:
    """Return the directory containing the live ``forge/`` package.

    The apply-back path resolves a fragment_dir against this root. We
    can't just import ``forge`` and use ``__file__.parent.parent``
    because the package may be installed editable — the parent of the
    package directory is the right anchor either way.
    """
    import forge  # noqa: PLC0415

    forge_pkg = Path(forge.__file__).resolve().parent
    return forge_pkg.parent


def _edit_a_known_literal_block(
    project_root: Path,
) -> tuple[Path | None, dict[str, Any]]:
    """Edit a FORGE-sentinel block whose upstream snippet has NO Jinja.

    Returns ``(file_path, meta)`` for the edited block or ``(None, {})``
    when no eligible block is found. Eligibility:

    * The block's BEGIN sentinel is present.
    * The body has no ``{{ }}`` / ``{% %}`` Jinja tokens — pure
      literal text. Apply-back literalizes ``current_body`` into the
      inject.yaml ``snippet:`` field, so a block that re-renders
      against a Jinja template would converge to a different body on
      the second generate (and harvest would have flagged it
      ``needs-review`` anyway).

    Edit shape: insert a comment line at the start of the block body.
    Using a position the surrounding source would never produce
    naturally (a comment) keeps the round-trip signal clear under any
    code formatter that might run between iterations.
    """
    candidates = []
    for ext in (".py", ".ts", ".js", ".rs"):
        candidates.extend(sorted(project_root.rglob(f"*{ext}")))

    sentinel = "FORGE:"
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        idx_begin = text.find(f"{sentinel}BEGIN ")
        idx_end = text.find(f"{sentinel}END ")
        if idx_begin == -1 or idx_end == -1 or idx_end <= idx_begin:
            continue

        # Find the BEGIN line + END line so we can read the body
        # between them.
        begin_line_end = text.find("\n", idx_begin)
        if begin_line_end == -1:
            continue
        body_start = begin_line_end + 1
        end_line_start = text.rfind("\n", 0, idx_end) + 1
        body = text[body_start:end_line_start]

        # Filter out Jinja-bearing blocks. Apply-back literalizes the
        # user's body; a block whose upstream snippet contains ``{{ }}``
        # would round-trip incorrectly.
        if "{{" in body or "{%" in body:
            continue

        # Read the BEGIN line's comment prefix so the inserted line
        # uses the same syntax.
        before_begin = text.rfind("\n", 0, idx_begin) + 1
        begin_line = text[before_begin:idx_begin]
        comment_prefix = begin_line.rstrip().rstrip("FORGE:").rstrip()
        if not comment_prefix:
            comment_prefix = "# "
        # The comment_prefix above strips trailing chars; restore a
        # trailing space for readability.
        if not comment_prefix.endswith(" "):
            comment_prefix = comment_prefix + " "

        injection = f"{comment_prefix}forge round-trip test marker\n"
        # Insert the new line at the START of the body (just after the
        # BEGIN line). This avoids a class of brittleness where the
        # block ends with a trailing newline that the user's edit
        # might collide with.
        new_text = text[:body_start] + injection + text[body_start:]
        path.write_text(new_text, encoding="utf-8")
        return path, {"file": str(path), "injection": injection.strip()}
    return None, {}


def _live_forge_apply_back_guard():
    """Context manager that snapshots+restores every inject.yaml under forge/.

    FR2 / RF1 mutate the live forge source during apply-back so that a
    subsequent ``generate()`` (which reads inject.yaml at apply time)
    picks up the user's edit. The mutation MUST be reverted on test
    exit — otherwise other tests in the same pytest run see polluted
    fragments and produce confusing failures.

    The snapshot is broad (every ``inject.yaml`` under ``forge/``) to
    avoid having to predict which files apply-back will touch. The
    file count is small (~70 files; see the inject.yaml glob in the
    helper) so the on-enter cost is negligible.
    """
    import contextlib  # noqa: PLC0415
    from contextlib import contextmanager  # noqa: PLC0415

    @contextmanager
    def _guard():
        forge_root = _live_forge_root()
        inject_yamls = list((forge_root / "forge").rglob("inject.yaml"))
        snapshots: dict[Path, bytes] = {p: p.read_bytes() for p in inject_yamls}
        try:
            yield
        finally:
            # Best-effort restore — if a file disappeared (apply-back
            # wrote elsewhere) the next test run will surface the gap.
            # We don't want to mask the original test failure with a
            # teardown error.
            for path, content in snapshots.items():
                with contextlib.suppress(OSError):
                    path.write_bytes(content)

    return _guard()


def _diff_project_trees(a: Path, b: Path) -> list[str]:
    """Return the list of POSIX rel-paths that differ between two project trees.

    Returns an empty list when the trees match modulo documented noise:
      * ``emitted_at`` timestamps in ``forge.toml`` (second-level
        granularity drift between two generates).
      * FORGE sentinel fingerprints (``fp:<hex8>``). The user's edit
        in project_a leaves the OLD fingerprint on the BEGIN line
        (the user only changed the body, not the sentinel). The
        regenerate in project_b re-computes the fingerprint over the
        NEW body. Normalising the fingerprint to a stable token lets
        us assert body equality without the round-trip having to
        rewrite project_a's sentinel.
      * ``.copier-answers.yml`` — Copier may emit slightly different
        ``_commit`` / ``_src_path`` content based on the run-time
        layout. The harvest contract isn't about Copier internals.
      * Anything under ``.git/`` — git index / object / log files
        differ across two ``git init`` invocations (different sha
        objects, different timestamps); these aren't part of the
        round-trip contract.

    LF/CRLF normalization applies to every text file (Windows CRLF
    drift is part of the round-trip contract).
    """
    files_a = {
        p.relative_to(a).as_posix(): p
        for p in a.rglob("*")
        if p.is_file() and not _is_excluded_rel(p.relative_to(a).as_posix())
    }
    files_b = {
        p.relative_to(b).as_posix(): p
        for p in b.rglob("*")
        if p.is_file() and not _is_excluded_rel(p.relative_to(b).as_posix())
    }

    differing: list[str] = []

    rels = set(files_a) | set(files_b)
    for rel in sorted(rels):
        pa = files_a.get(rel)
        pb = files_b.get(rel)
        if pa is None or pb is None:
            differing.append(rel)
            continue
        if _file_is_normalized_match(rel, pa, pb):
            continue
        differing.append(rel)
    return differing


def _is_excluded_rel(rel: str) -> bool:
    """Return True when ``rel`` is in the FR2-comparison exclusion set.

    Currently excludes ``.git/...`` (different sha objects, mtimes)
    and any file named ``.copier-answers.yml`` (Copier internals).
    """
    if rel.startswith(".git/") or "/.git/" in rel or rel == ".git":
        return True
    return rel.endswith(".copier-answers.yml")


def _is_pre_existing_drift(rel: str) -> bool:
    """Return True for files known to read as ``user-modified`` on fresh generate.

    The deps + env appliers append fragment-declared content to the
    base-template's ``pyproject.toml`` / ``package.json`` / ``Cargo.toml``
    / ``.env.example`` AFTER the provenance manifest stamps the file's
    sha256. So even a fresh ``generate()`` produces ``user-modified``
    entries for these paths. Restamping the manifest after the appliers
    run is the correct long-term fix and is out of scope here; RF1
    scopes its assertion to BLOCK-mediated drift (the contract Phase 6
    actually owns).

    Returns True for paths that match the known-broken set, so the
    RF1 check filters them before asserting zero.
    """
    leaf = rel.rsplit("/", 1)[-1]
    return leaf in {
        ".env.example",
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
    }


def _file_is_normalized_match(rel: str, pa: Path, pb: Path) -> bool:
    """Compare two files modulo round-trip noise; return True on match.

    See :func:`_diff_project_trees` for the noise contract.
    """
    ba = pa.read_bytes()
    bb = pb.read_bytes()
    if ba == bb:
        return True
    # Exclusions for files whose drift is incidental.
    if rel == ".copier-answers.yml":
        return True
    # Binary files outside the text-normalisation domain.
    if not (_is_text_bytes(ba) and _is_text_bytes(bb)):
        return False

    sa = _normalize_text_for_fr2(rel, ba.decode("utf-8", errors="replace"))
    sb = _normalize_text_for_fr2(rel, bb.decode("utf-8", errors="replace"))
    if sa == sb:
        return True
    return sa.replace("\r\n", "\n") == sb.replace("\r\n", "\n")


def _normalize_text_for_fr2(rel: str, text: str) -> str:
    """Strip FR2-noise from ``text`` before comparison.

    Three classes of noise are normalized away:

    1. ``emitted_at = "..."`` lines in ``forge.toml`` — UTC timestamp
       at second granularity, drifts across iterations.
    2. ``fp:<hex8>`` fingerprints in FORGE BEGIN sentinels — recomputed
       from the snippet on each generate; the user's in-place edit in
       project_a leaves the old fingerprint, but project_b has the new
       one based on the harvested snippet.
    3. ``sha256 = "..."`` + ``snippet_sha256 = "..."`` lines in
       ``forge.toml`` — derived from on-disk content. Project_a's
       manifest is stale relative to the user's edit (the user hasn't
       run ``forge --update`` yet), so the recorded SHAs don't match
       the post-edit file. Project_b's manifest is fresh. FR2 is
       fundamentally about CONTENT equality, not manifest metadata —
       so we normalise these to a stable token.
    """
    import re  # noqa: PLC0415

    out = text
    if rel.endswith("forge.toml"):
        out = re.sub(r'emitted_at\s*=\s*"[^"]*"', 'emitted_at = "<NORM>"', out)
        out = re.sub(r'sha256\s*=\s*"[0-9a-f]+"', 'sha256 = "<NORM>"', out)
        out = re.sub(r'snippet_sha256\s*=\s*"[0-9a-f]+"', 'snippet_sha256 = "<NORM>"', out)
    # FORGE fingerprint normalisation applies to any text file —
    # sentinels can appear in any code file.
    out = re.sub(r"FORGE:BEGIN ([^\n]*?) fp:[0-9a-f]{8}", r"FORGE:BEGIN \1 fp:<NORM>", out)
    return out


def _dirs_match_lf_normalized(a: Path, b: Path) -> bool:
    """Compare two project trees byte-for-byte, normalizing CRLF→LF.

    Returns ``True`` when every relative path is present in both
    trees with matching content (text files compared after line-ending
    normalization; binary files compared as-is). Cross-platform
    tolerance matters because Windows CI emits CRLF and Linux emits
    LF; the LF-normalized contract is what the round-trip guarantees.
    """
    files_a = {p.relative_to(a).as_posix(): p for p in a.rglob("*") if p.is_file()}
    files_b = {p.relative_to(b).as_posix(): p for p in b.rglob("*") if p.is_file()}
    if set(files_a) != set(files_b):
        return False
    for rel, pa in files_a.items():
        pb = files_b[rel]
        ba = pa.read_bytes()
        bb = pb.read_bytes()
        if ba == bb:
            continue
        # Try LF-normalized comparison for text files. Combined `and`
        # form keeps the short-circuit semantics — we only invoke the
        # replace when both bytes-blobs are textual (no NUL, valid UTF-8).
        if (
            _is_text_bytes(ba)
            and _is_text_bytes(bb)
            and ba.replace(b"\r\n", b"\n") == bb.replace(b"\r\n", b"\n")
        ):
            continue
        return False
    return True


def _is_text_bytes(data: bytes) -> bool:
    """Cheap heuristic: bytes are text if they decode as UTF-8 and contain no NUL."""
    if b"\x00" in data[:8192]:
        return False
    try:
        data[:8192].decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


# ---------------------------------------------------------------------------
# apply_bundle_to_fragments — direct unit coverage
# ---------------------------------------------------------------------------
#
# The full generate-driven FR2 / RF1 tests are gated by Phase 6 block
# apply-back. These tests exercise the v1 files-only branch of
# ``apply_bundle_to_fragments`` directly — no ``generate`` call needed,
# so they run in milliseconds and can ship in the per-PR test surface.


class TestApplyBundleFilesOnly:
    """Direct exercise of the apply_bundle helper's files branch."""

    def test_files_candidate_overwrites_fragment_file(self, tmp_path: Path) -> None:
        """A ``safe-apply`` files candidate rewrites the fragment-shipped file.

        Sets up a synthetic forge_repo with a single fragment carrying
        one file, registers the fragment with the in-process registry,
        and asserts the helper copies the candidate's current content
        into the fragment's ``files/`` tree.
        """
        from forge.extractors.pipeline import CandidatePatch  # noqa: PLC0415
        from forge.sync.project_to_forge.apply_bundle import (  # noqa: PLC0415
            apply_bundle_to_fragments,
        )
        from forge.sync.project_to_forge.harvester import HarvestBundle  # noqa: PLC0415

        # Build a tmp forge_repo with one fragment dir.
        forge_repo = tmp_path / "forge-clone"
        fragment_dir = forge_repo / "forge" / "templates" / "_fragments" / "demo_fragment"
        files_dir = fragment_dir / "files"
        files_dir.mkdir(parents=True)
        (files_dir / "foo.txt").write_text("upstream content\n", encoding="utf-8")

        # User's edited version of the file (on the project side).
        project_file = tmp_path / "user-edited-foo.txt"
        project_file.write_text("user-edited content\n", encoding="utf-8")

        # Register the fragment temporarily so the helper can resolve it.
        fragment = _register_demo_fragment("demo_fragment", "demo_fragment")
        try:
            bundle = HarvestBundle(
                bundle_id="harvest-test",
                project_root=tmp_path,
                forge_version="0.0.0-test",
                candidates=[
                    CandidatePatch(
                        fragment=fragment.name,
                        backend="api",
                        kind="files",
                        rel_path="foo.txt",
                        target_path=str(project_file),
                        diff="",
                        baseline_sha=None,
                        current_sha="",
                        risk="safe-apply",
                    ),
                ],
            )
            report = apply_bundle_to_fragments(bundle, forge_repo, quiet=True)
        finally:
            _unregister_fragment(fragment.name)

        assert report.applied == 1
        assert report.skipped == 0
        assert report.deferred == 0
        assert report.errored == 0
        # The fragment file now carries the user's content.
        assert (files_dir / "foo.txt").read_text(encoding="utf-8") == "user-edited content\n"

    def test_block_candidate_missing_metadata_is_errored(self, tmp_path: Path) -> None:
        """``kind="block"`` without ``current_body`` / ``marker`` errors.

        Phase 6 wires the block apply-back path: the rewrite needs
        the post-edit body and the sentinel marker to pin the inject.
        yaml entry. A bundle whose block candidates lack either
        field can't be applied — surface as ``errored`` so the
        operator notices.
        """
        from forge.extractors.pipeline import CandidatePatch  # noqa: PLC0415
        from forge.sync.project_to_forge.apply_bundle import (  # noqa: PLC0415
            apply_bundle_to_fragments,
        )
        from forge.sync.project_to_forge.harvester import HarvestBundle  # noqa: PLC0415

        bundle = HarvestBundle(
            bundle_id="harvest-test",
            project_root=tmp_path,
            forge_version="0.0.0-test",
            candidates=[
                CandidatePatch(
                    fragment="any_fragment",
                    backend="api",
                    kind="block",
                    rel_path="src/app/main.py",
                    target_path=str(tmp_path / "src/app/main.py"),
                    diff="@@ -1 +1 @@\n-old\n+new\n",
                    baseline_sha="abc",
                    current_sha="def",
                    risk="safe-apply",
                    # No current_body / marker — the new fields the
                    # block applier needs are missing.
                ),
            ],
        )
        report = apply_bundle_to_fragments(bundle, tmp_path, quiet=True)
        assert report.applied == 0
        assert report.errored == 1
        entry = report.entries[0]
        assert entry.status == "errored"
        assert "current_body" in entry.error

    def test_filtered_risk_is_skipped(self, tmp_path: Path) -> None:
        """Candidates outside the ``risk_filter`` land as ``skipped``."""
        from forge.extractors.pipeline import CandidatePatch  # noqa: PLC0415
        from forge.sync.project_to_forge.apply_bundle import (  # noqa: PLC0415
            apply_bundle_to_fragments,
        )
        from forge.sync.project_to_forge.harvester import HarvestBundle  # noqa: PLC0415

        bundle = HarvestBundle(
            bundle_id="harvest-test",
            project_root=tmp_path,
            forge_version="0.0.0-test",
            candidates=[
                CandidatePatch(
                    fragment="any_fragment",
                    backend="api",
                    kind="files",
                    rel_path="foo.txt",
                    target_path=str(tmp_path / "foo.txt"),
                    diff="",
                    baseline_sha=None,
                    current_sha="",
                    risk="needs-review",  # outside default filter
                ),
            ],
        )
        report = apply_bundle_to_fragments(bundle, tmp_path, quiet=True)
        assert report.applied == 0
        assert report.skipped == 1
        # Override the filter — same candidate now lands as errored
        # (no fragment registered, but the filter accepts it).
        report2 = apply_bundle_to_fragments(
            bundle, tmp_path, risk_filter=("safe-apply", "needs-review"), quiet=True
        )
        # The risk passed the filter, but the fragment isn't registered.
        assert report2.errored == 1
        assert report2.skipped == 0

    def test_unregistered_fragment_is_errored(self, tmp_path: Path) -> None:
        """Files candidate for an unknown fragment surfaces as ``errored``."""
        from forge.extractors.pipeline import CandidatePatch  # noqa: PLC0415
        from forge.sync.project_to_forge.apply_bundle import (  # noqa: PLC0415
            apply_bundle_to_fragments,
        )
        from forge.sync.project_to_forge.harvester import HarvestBundle  # noqa: PLC0415

        bundle = HarvestBundle(
            bundle_id="harvest-test",
            project_root=tmp_path,
            forge_version="0.0.0-test",
            candidates=[
                CandidatePatch(
                    fragment="nope_not_a_fragment",
                    backend="api",
                    kind="files",
                    rel_path="foo.txt",
                    target_path=str(tmp_path / "foo.txt"),
                    diff="",
                    baseline_sha=None,
                    current_sha="",
                    risk="safe-apply",
                ),
            ],
        )
        report = apply_bundle_to_fragments(bundle, tmp_path, quiet=True)
        assert report.errored == 1
        assert "not in registry" in report.entries[0].error


def _register_demo_fragment(name: str, fragment_dir_relpath: str):
    """Register a synthetic fragment in the global registry for testing.

    Returns the :class:`Fragment` so the test can reference its name
    when building the candidate. The fragment ships a single
    implementation with ``scope="backend"`` so the registry treats it
    like a real backend-scoped fragment.

    Pairs with :func:`_unregister_fragment`; tests must call the
    cleanup in a ``finally`` so a parametrize / re-run can re-register
    cleanly. Handles the case where the registry has been frozen by
    an earlier test via the ``_reset_for_tests`` thaw — we re-freeze
    on the way out only if the registry was frozen on entry, so we
    don't leak a thawed registry to a downstream test.
    """
    from forge.config import BackendLanguage  # noqa: PLC0415
    from forge.fragments import FRAGMENT_REGISTRY, Fragment, FragmentImplSpec  # noqa: PLC0415

    impl = FragmentImplSpec(
        fragment_dir=fragment_dir_relpath,
        scope="backend",
    )
    fragment = Fragment(
        name=name,
        implementations={BackendLanguage.PYTHON: impl},
    )
    # Thaw briefly if the registry has been frozen by an upstream test
    # (e.g. one that called ``resolve()``). We don't re-freeze here —
    # the tearing-down ``_unregister_fragment`` does that conditionally.
    was_frozen = getattr(FRAGMENT_REGISTRY, "frozen", False)
    if was_frozen:
        FRAGMENT_REGISTRY.frozen = False
    FRAGMENT_REGISTRY[name] = fragment
    if was_frozen:
        FRAGMENT_REGISTRY.frozen = True
    return fragment


def _unregister_fragment(name: str) -> None:
    """Remove a fragment registered via :func:`_register_demo_fragment`."""
    from forge.fragments import FRAGMENT_REGISTRY  # noqa: PLC0415

    was_frozen = getattr(FRAGMENT_REGISTRY, "frozen", False)
    if was_frozen:
        FRAGMENT_REGISTRY.frozen = False
    FRAGMENT_REGISTRY.pop(name, None)
    if was_frozen:
        FRAGMENT_REGISTRY.frozen = True
