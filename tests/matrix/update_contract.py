"""Lane E contract: ``forge --update`` modes + ``forge --harvest`` exit code.

For each scenario, this exercises the three update modes documented in
the README (``--mode merge`` / ``--mode skip`` / ``--mode overwrite``)
by:

1. Generating into ``mode-<mode>/<slug>/`` for mode isolation (overwrite
   would clobber state for the next mode if shared); the actual
   project root is the generator's return value, not a constructed
   path (``generate()`` slugifies ``project_name`` into the dir name).
2. Staging a sentinel edit in a *fragment-authored file* — found via
   ``forge.toml``'s provenance table, mirroring the heuristic in
   ``tests/test_updater.py::_find_fragment_file``. The file-level
   ``--mode`` knob controls collision behaviour for whole-file copies
   from a fragment's ``files/`` tree, so the assertion target must be
   a file with ``origin = "fragment"`` (not an injection-block body in
   a base-template file, which would be governed by injection-zone
   three-way-merge semantics independent of ``--mode``).
3. Shelling out to
   ``python -m forge --update --mode <mode> --project-path <p>``.
4. Asserting the per-mode contract:

   * **skip** — file MUST equal the pre-update bytes (the pre-1.1
     behaviour: user content preserved unconditionally).
   * **overwrite** — sentinel MUST be absent from the file (fragment
     content wins, "my edits be damned" escape hatch).
   * **merge** — either the sentinel survives in the file, OR a
     ``<file>.forge-merge`` sidecar was written (three-way decide
     against the manifest baseline).
5. Re-running ``--update`` with the same mode — must exit 0
   (idempotency probe).

Finally runs ``python -m forge --harvest --harvest-out=- --project-path
<merge-project>`` once and asserts:

* Exit code is 0 (clean) OR 11 (``EXIT_VERIFY_CONFLICT`` — conflict
  candidates present; the bundle was still written, the exit code
  surfaces a conflict signal but a parseable bundle is fine).
* Stdout is valid JSON with a ``candidates`` key (the
  :meth:`HarvestBundle.to_dict` shape).

Uses ``subprocess.run([sys.executable, "-m", "forge", ...])`` so the
same argparse / builder / dispatcher path real users hit gets
exercised — complementary to lane D's direct Python-API round-trip.
Drops weld-* SDK stubs into ``<project>/sdks/`` via
``_inject_weld_stubs`` from the runner so ``forge --update`` resolves
the same package set as lanes B/C (the auth fragment's manifest entries
depend on the stubs being present even for a no-op re-apply).

The plan that motivated this lane lives at
``docs/superpowers/plans/immutable-napping-bear.md`` (WS4).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

# Re-use the runner's record types so the dispatcher and the contract
# emit/consume the same shape. Lane E imports the runner; runner imports
# this module lazily inside ``run_lane_update`` to avoid a circular load.
from tests.matrix.runner import LaneResult, Scenario  # noqa: TID252

Mode = Literal["merge", "skip", "overwrite"]
MODES: tuple[Mode, ...] = ("merge", "skip", "overwrite")

# Cap each subprocess at 600s. First ``--update`` on a fresh project
# runs ``uv sync`` end-to-end (the template's post-generate step is
# already paid by lane A; the in-update template-update step may pull
# more wheels), so a 10-minute ceiling covers cold-cache CI without
# letting a hung subprocess starve the rest of the matrix run.
_FORGE_TIMEOUT_SECONDS = 600

# Sentinel injected into the user-editable body of the fragment-
# authored file. Distinctive enough that the assertions can grep for
# it without false positives, and ASCII so any text-file encoding
# round-trips.
_SENTINEL = b"# forge lane-E update CI marker\n"


def run_update_contract(
    scenario: Scenario,
    build_config: Callable[[dict[str, Any]], Any],
    inject_stubs: Callable[[Path], None],
) -> LaneResult:
    """Drive the three update modes + a single harvest probe against ``scenario``.

    ``build_config`` is the runner's ``_project_config_from_dict`` — the
    same ingestion path the CLI uses, so the runner and the lane stay
    in lock-step with config-file merge rules. ``inject_stubs`` is the
    runner's ``_inject_weld_stubs`` so the matrix-CI SDK shims drop
    into ``<project>/sdks/`` before ``--update`` resolves them.

    Returns a :class:`LaneResult` consistent with the other lanes.
    Any per-mode or harvest failure is surfaced via ``details``; the
    runner stays alive across the full scenario set (no exceptions
    propagate out of this function).
    """
    start = perf_counter()
    tmp = Path(tempfile.mkdtemp(prefix=f"forge-matrix-{scenario.name}-update-"))
    try:
        failures: list[str] = []
        # Capture per-mode project roots so the harvest probe below can
        # target the merge-mode project specifically. ``generate()``
        # slugifies ``project_name`` into the directory name (not the
        # caller's ``output_dir`` child), so the realised path can only
        # be known after ``generate()`` returns.
        project_roots: dict[Mode, Path | None] = {}
        for mode in MODES:
            mode_parent = tmp / f"mode-{mode}"
            mode_parent.mkdir(parents=True, exist_ok=True)
            err, project_root = _drive_mode(scenario, mode, mode_parent, build_config, inject_stubs)
            project_roots[mode] = project_root
            if err:
                failures.append(f"mode={mode}: {err}")

        # Single harvest probe — bundle-content correctness is covered
        # by lane D + tests/test_harvest_invariants.py. Here we only
        # assert the CLI surface exits cleanly (or with the documented
        # conflict signal) and emits a parseable JSON bundle on stdout.
        merge_project = project_roots.get("merge")
        if merge_project is None:
            failures.append("harvest: merge-mode project not generated")
        else:
            harvest_err = _drive_harvest(merge_project)
            if harvest_err:
                failures.append(f"harvest: {harvest_err}")

        status: Literal["ok", "fail"] = "fail" if failures else "ok"
        return LaneResult(
            scenario=scenario.name,
            lane="update",
            status=status,
            duration_ms=int((perf_counter() - start) * 1000),
            details=("; ".join(failures) if failures else ""),
        )
    finally:
        # Windows can hold file handles open briefly after Copier
        # finishes (NTFS lazy release); ignore_errors keeps the lane
        # robust without leaking tmp dirs in CI.
        shutil.rmtree(tmp, ignore_errors=True)


def _drive_mode(
    scenario: Scenario,
    mode: Mode,
    output_dir: Path,
    build_config: Callable[[dict[str, Any]], Any],
    inject_stubs: Callable[[Path], None],
) -> tuple[str | None, Path | None]:
    """Generate → edit fragment-authored file → ``--update --mode <mode>`` → assert.

    Then re-run ``--update`` with the same mode for the idempotency
    probe. Returns ``(error, project_root)`` — ``error`` is ``None``
    on success or a human-readable failure label; ``project_root`` is
    the realised generator-output directory under ``output_dir`` (or
    ``None`` when generation itself failed). The caller uses
    ``project_root`` to target the harvest probe at the merge-mode
    project specifically.

    ``output_dir`` is the parent into which the generator's slugified
    project directory will land; the actual project root comes from
    the ``generate()`` return value, not from constructing a path.
    """
    from forge.errors import ForgeError  # noqa: PLC0415
    from forge.generator import generate  # noqa: PLC0415

    cfg = dict(scenario.config)
    cfg["output_dir"] = str(output_dir)
    # Give each mode a distinct project_name so the generator emits
    # into <output_dir>/<project_name-slug>/ predictably. We then
    # resolve the actual project_root from the generator's return
    # value rather than guessing the slugified path.
    cfg["project_name"] = f"{scenario.config.get('project_name', scenario.name)} {mode}"
    try:
        project_config = build_config(cfg)
        project_config.validate()
        project_root = generate(project_config, quiet=True, dry_run=False)
    except (ValueError, ForgeError) as e:
        return f"generate failed: {type(e).__name__}: {e}", None

    inject_stubs(project_root)

    edited = _stage_edit(project_root)
    if edited is None:
        # No fragment-authored file in the generated project — the
        # ``--mode`` matrix has no surface to exercise here (purely
        # base-template scenario). Treat as a soft success; we still
        # exercise the no-op ``--update`` path below so the CLI
        # surface is touched.
        result = _run_forge(["--update", "--mode", mode, "--project-path", str(project_root)])
        if result.returncode != 0:
            return (
                f"--update --mode {mode} on no-fragment-file project "
                f"exit {result.returncode}: {_tail(result)}",
                project_root,
            )
        return None, project_root
    original_bytes = edited.read_bytes()

    # First --update — the contract assertion target.
    result = _run_forge(["--update", "--mode", mode, "--project-path", str(project_root)])
    if result.returncode != 0:
        return (
            f"--update --mode {mode} exit {result.returncode}: {_tail(result)}",
            project_root,
        )

    contract_err = _assert_mode_contract(mode, edited, original_bytes, project_root)
    if contract_err:
        return contract_err, project_root

    # Idempotency probe — second --update with the same mode must exit 0.
    # (The merge-mode sidecar from the first run is allowed to persist;
    # the second --update should be a no-op rather than re-emit it.)
    result2 = _run_forge(["--update", "--mode", mode, "--project-path", str(project_root)])
    if result2.returncode != 0:
        return (
            f"second --update --mode {mode} exit {result2.returncode}: {_tail(result2)}",
            project_root,
        )
    return None, project_root


def _assert_mode_contract(
    mode: Mode,
    edited: Path,
    original_bytes: bytes,
    project_root: Path,
) -> str | None:
    """Assert the per-mode post-update contract on the edited file.

    Returns ``None`` on success, a human-readable failure label on
    failure. ``original_bytes`` is the file content *after* the
    sentinel was injected and *before* ``--update`` ran.
    """
    rel = edited.relative_to(project_root).as_posix()
    try:
        post = edited.read_bytes()
    except FileNotFoundError:
        # ``overwrite`` shouldn't delete the file, but a fragment might
        # legitimately re-author it as part of a re-apply. Treat the
        # absence as overwrite-equivalent: the sentinel can't survive.
        if mode == "overwrite":
            return None
        return f"{mode} mode deleted target file {rel}"

    if mode == "skip":
        if post != original_bytes:
            return (
                f"skip mode mutated {rel} ({len(original_bytes)} -> "
                f"{len(post)} bytes); pre-1.1 behaviour expects untouched"
            )
        return None

    if mode == "overwrite":
        if _SENTINEL in post:
            return (
                f"overwrite mode preserved user sentinel in {rel}; "
                "fragment content was expected to clobber the edit"
            )
        return None

    # mode == "merge" — either the edit survives in-place (no
    # baseline drift -> three-way merge collapsed cleanly back to the
    # user's body) or a .forge-merge sidecar was emitted (conflict
    # awaiting resolution; user file may have been replaced by
    # fragment content in that case). Both are part of the documented
    # merge contract; only a silent drop of the edit without a
    # sidecar is a violation.
    if _SENTINEL in post:
        return None
    sidecar = edited.with_suffix(edited.suffix + ".forge-merge")
    if sidecar.exists():
        return None
    return (
        f"merge mode lost sentinel in {rel} with no .forge-merge sidecar; "
        "user edit was silently dropped"
    )


def _drive_harvest(project_root: Path) -> str | None:
    """Run ``forge --harvest --harvest-out=-`` and assert JSON-parseable output.

    Accepts exit codes 0 (clean) and ``EXIT_VERIFY_CONFLICT`` (= 11 —
    conflict candidates present; the bundle is still written). Any
    other exit code or a non-JSON stdout is a failure.
    """
    if not project_root.exists():
        return "merge-mode project_root missing (prior mode failure)"

    from forge.errors import EXIT_VERIFY_CONFLICT  # noqa: PLC0415

    # ``--quiet`` suppresses ``harvest_project()``'s progress chatter so
    # stdout is pure JSON. Without it, the CLI prints lines like
    # ``[harvest] N candidate(s) across F fragment(s); bundle_id=...``
    # to stdout before the JSON envelope, breaking ``json.loads``.
    result = _run_forge(
        [
            "--harvest",
            "--harvest-out=-",
            "--quiet",
            "--project-path",
            str(project_root),
        ]
    )
    if result.returncode not in (0, EXIT_VERIFY_CONFLICT):
        return (
            f"harvest exit {result.returncode} (expected 0 or "
            f"{EXIT_VERIFY_CONFLICT}): {_tail(result)}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        # Truncate stdout in the failure label so the lane report stays
        # readable even on a tens-of-KB bundle.
        head = result.stdout[:200].replace("\n", " ")
        return f"harvest stdout not JSON: {e}; head={head!r}"
    if not isinstance(payload, dict) or "candidates" not in payload:
        keys = list(payload) if isinstance(payload, dict) else f"<{type(payload).__name__}>"
        return f"harvest payload missing 'candidates' key: keys={keys}"
    return None


def _run_forge(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Invoke the forge CLI as ``python -m forge`` for argparse coverage.

    Wraps :class:`subprocess.TimeoutExpired` and :class:`FileNotFoundError`
    so a runaway forge run or a missing Python interpreter surface as
    a non-zero ``CompletedProcess`` rather than crashing the runner —
    same pattern as ``runner._run_frontend_step`` (WS2). The synthetic
    failure result carries the timeout / exec error in ``stderr`` so
    ``_tail`` formats it consistently with real subprocess failures.
    """
    try:
        return subprocess.run(  # noqa: S603
            [sys.executable, "-m", "forge", *args],
            capture_output=True,
            text=True,
            timeout=_FORGE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        # Surface as a synthetic failed CompletedProcess so the call
        # site's exit-code check fires uniformly. 124 is the GNU
        # ``timeout(1)`` exit code — a self-documenting signal.
        return subprocess.CompletedProcess(
            args=e.cmd if isinstance(e.cmd, list) else list(e.cmd or []),
            returncode=124,
            stdout=(
                e.stdout.decode("utf-8", "replace")
                if isinstance(e.stdout, bytes)
                else (e.stdout or "")
            ),
            stderr=f"forge subprocess timed out after {_FORGE_TIMEOUT_SECONDS}s",
        )
    except FileNotFoundError as e:
        return subprocess.CompletedProcess(
            args=[sys.executable, "-m", "forge", *args],
            returncode=127,
            stdout="",
            stderr=f"forge subprocess exec failed: {e}",
        )


def _stage_edit(project_root: Path) -> Path | None:
    """Inject the lane-E sentinel into the body of a fragment-authored file.

    Mirrors ``tests/test_updater.py::_find_fragment_file``: walks the
    project's ``forge.toml`` provenance table for the first entry with
    ``origin = "fragment"`` that resolves to an existing text file with
    a fragment-friendly extension. Overwrites the file with a body that
    embeds the sentinel — the simplest way to guarantee the sentinel is
    present and the file content differs from the fragment baseline so
    the ``--mode`` branch actually engages.

    Returns the edited path on success, ``None`` when no fragment-
    authored file exists in the project (the lane treats that as a
    vacuous success — the ``--update`` no-op path still gets exercised
    by the caller).
    """
    from forge.sync.manifest import read_forge_toml  # noqa: PLC0415

    manifest = project_root / "forge.toml"
    if not manifest.is_file():
        return None
    try:
        data = read_forge_toml(manifest)
    except Exception:  # noqa: BLE001 — corrupt manifest is a generator bug, not a lane-E bug.
        return None

    for rel, entry in data.provenance.items():
        if entry.get("origin") != "fragment":
            continue
        path = project_root / rel
        if not path.is_file() or path.suffix not in (".py", ".js", ".ts", ".rs", ".md"):
            continue
        # Overwrite with a one-line body that embeds the sentinel. We
        # don't try to preserve the original content — for the
        # ``--mode`` matrix the user-edit-is-different invariant is
        # what matters; the baseline is recorded by
        # ``classify_project_state`` reading the manifest, not by the
        # on-disk pre-edit body.
        try:
            path.write_bytes(_SENTINEL)
        except OSError:
            continue
        return path
    return None


def _tail(result: subprocess.CompletedProcess[str]) -> str:
    """Return the last 3 lines of stderr (or stdout) for a failure label.

    Keeps lane-E failure ``details`` short enough to render readably in
    the matrix dashboard while still carrying enough context for triage.
    """
    stream = (result.stderr or "").strip() or (result.stdout or "").strip()
    if not stream:
        return "<no output>"
    return " | ".join(stream.splitlines()[-3:])
