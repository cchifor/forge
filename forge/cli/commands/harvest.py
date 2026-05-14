"""``forge --harvest`` — reverse-direction extraction CLI dispatcher.

Phase 4 of the bidirectional-sync plan. Counterpart of ``forge --update``
(forward apply) and ``forge --verify`` (read-only drift). The dispatcher
resolves the project root, hands off to :func:`harvest_project`,
optionally writes the bundle to disk, and maps the result to an exit
code:

* ``0`` — bundle written cleanly (or empty bundle — no harvest needed).
* ``5`` — pre-condition failure (missing forge.toml; missing
  ``$FORGE_REPO`` for ``--emit-pr``; dirty forge_repo working tree).
* ``11`` — at least one ``conflict`` candidate present. The bundle is
  still written; the exit code surfaces the conflict to CI gates.

Phase 6 close: ``--emit-pr={branch,github}`` chains
:func:`forge.sync.project_to_forge.emit_pr.emit_pr` after the harvest,
committing candidates to a branch in ``$FORGE_REPO`` (and optionally
opening the PR via ``gh``). The accept-harvested verb stays a
separate dispatch path.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Literal, cast

from forge import telemetry
from forge.errors import EXIT_VERIFY_CONFLICT, PROVENANCE_MANIFEST_MISSING, ProvenanceError
from forge.sync.project_to_forge.emit_pr import emit_pr
from forge.sync.project_to_forge.harvester import HarvestBundle, harvest_project

# Exit code when the harvest target has no forge.toml. Mirrors the
# ``--verify`` dispatcher so the harvest verb's exit codes stay
# consistent with the broader CLI taxonomy (5 = manifest IO failure).
_EXIT_MANIFEST_MISSING = 5

# Same code reused for --emit-pr pre-condition failures (missing
# --forge-repo, dirty working tree, gh not installed). Keeping the code
# narrow means CI gates that already key on 5 cover the new failure
# modes without a separate branch.
_EXIT_EMIT_PR_PRECONDITION = 5


def _run_harvest(args: argparse.Namespace) -> int:
    """Dispatch ``forge --harvest``. Returns the exit code.

    Resolves ``--project-path`` (defaulting to the current directory),
    invokes :func:`harvest_project`, prints the bundle in JSON shape
    when ``--harvest-out=-``, and returns 0 / 11 based on whether any
    ``conflict`` candidates were emitted. Never raises — every failure
    path surfaces as a non-zero return.

    When ``--emit-pr`` is set, additionally commits the bundle's
    candidates to a branch in ``$FORGE_REPO`` (or ``--forge-repo PATH``)
    via :func:`emit_pr`. Pre-condition failures surface as exit code 5
    without touching the forge_repo. The bundle is always materialised
    on disk before the emit step runs.
    """
    project_root = Path(getattr(args, "project_path", ".") or ".").resolve()
    out_dir_arg = getattr(args, "harvest_out", ".forge-harvest")
    out_dir: Path | None = None if out_dir_arg == "-" else Path(out_dir_arg).resolve()

    scope_arg = getattr(args, "harvest_scope", None)
    scope: tuple[str, ...] | None = (
        tuple(s.strip() for s in scope_arg.split(",") if s.strip()) if scope_arg else None
    )

    include_arg = getattr(args, "harvest_include", "all")
    include: tuple[str, ...] = (
        ("files", "blocks", "deps", "env") if include_arg == "all" else (include_arg,)
    )

    interactive = bool(getattr(args, "harvest_interactive", False))
    json_output = bool(getattr(args, "json_output", False))
    emit_pr_mode = str(getattr(args, "emit_pr", "off") or "off")
    # In streaming-stdout JSON mode the harvester suppresses progress
    # output; emit-pr piggybacks on the same flag to keep stdout pure
    # JSON when ``--harvest-out=-`` is active.
    quiet = (
        bool(getattr(args, "quiet", False))
        or json_output
        or (emit_pr_mode != "off" and out_dir is None)
    )

    try:
        bundle = harvest_project(
            project_root,
            out_dir=out_dir,
            scope=scope,
            include=include,
            interactive=interactive,
            quiet=quiet,
        )
    except ProvenanceError as e:
        # The harvester raises ProvenanceError(PROVENANCE_MANIFEST_MISSING)
        # when no forge.toml is present at project_root. Surface a
        # structured error so JSON consumers can branch on a known shape,
        # then exit with the manifest-missing code (5).
        if e.code == PROVENANCE_MANIFEST_MISSING:
            if out_dir is None:
                sys.stdout.write(json.dumps({"error": f"no forge.toml at {project_root}"}) + "\n")
            else:
                sys.stderr.write(f"forge --harvest: no forge.toml at {project_root}\n")
            return _EXIT_MANIFEST_MISSING
        raise

    # Streaming JSON mode: write the bundle envelope to stdout instead
    # of materialising a directory. Symmetric to ``forge --verify --json``.
    # Suppress when --emit-pr is set; the emit report replaces the
    # bundle envelope as the stdout payload.
    if out_dir is None and emit_pr_mode == "off":
        sys.stdout.write(json.dumps(bundle.to_dict(), indent=2) + "\n")

    _emit_harvest_telemetry(project_root, bundle)

    # --emit-pr chain: optionally commit candidates to a branch in the
    # forge clone (and open a PR in ``github`` mode).
    if emit_pr_mode != "off":
        return _run_emit_pr_chain(
            args=args,
            bundle=bundle,
            emit_pr_mode=emit_pr_mode,
            json_output=json_output,
            quiet=quiet,
        )

    if not bundle.candidates:
        return 0

    # Conflicts produce a non-zero exit so CI gates that wrap harvest
    # see the failure even when the bundle directory is materialised.
    if any(c.risk == "conflict" for c in bundle.candidates):
        return EXIT_VERIFY_CONFLICT

    return 0


def _emit_harvest_telemetry(project_root: Path, bundle: HarvestBundle) -> None:
    """Emit ``harvest.ran`` + per-candidate ``harvest.candidate_emitted``.

    Aggregate counts go on the ``harvest.ran`` event so a remote ingest
    in ``minimal`` mode can answer "how often did harvest emit X?"
    without ever seeing fragment names. Per-candidate events carry the
    fragment name in ``full`` mode; ``minimal`` mode drops it.

    Item 6: emit ``harvest.option_promotion_suggested`` for every
    candidate carrying a non-empty ``option_promotion`` payload — one
    event per detected :class:`LiteralEdit`, with the literal's
    ``kind`` + ``new_value`` so a maintainer can aggregate "which kinds
    of literals do users most often patch in this fragment?" The
    ``new_value`` field is dropped by the ``minimal`` field filter
    because it's not on the allowlist; only the ``kind`` aggregate
    survives a remote-friendly emission.
    """
    by_kind: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    for c in bundle.candidates:
        by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
        by_risk[c.risk] = by_risk.get(c.risk, 0) + 1

    telemetry.emit(
        telemetry.EVENT_HARVEST_RAN,
        project_root=project_root,
        candidate_count_by_kind=by_kind,
        candidate_count_by_risk=by_risk,
        entry_count=len(bundle.candidates),
    )
    for c in bundle.candidates:
        telemetry.emit(
            telemetry.EVENT_HARVEST_CANDIDATE,
            project_root=project_root,
            kind=c.kind,
            risk=c.risk,
            fragment=c.fragment,
            rel_path=c.rel_path,
        )
        for edit in c.option_promotion:
            telemetry.emit(
                telemetry.EVENT_HARVEST_OPTION_PROMOTION_SUGGESTED,
                project_root=project_root,
                fragment=c.fragment,
                kind=edit.kind,
                value=edit.new_value,
            )


def _run_emit_pr_chain(
    *,
    args: argparse.Namespace,
    bundle,  # noqa: ANN001 — typed as HarvestBundle but kept un-imported here.
    emit_pr_mode: str,
    json_output: bool,
    quiet: bool,
) -> int:
    """Resolve --forge-repo / $FORGE_REPO and call :func:`emit_pr`.

    Returns the dispatcher's exit code. Splits out of ``_run_harvest``
    to keep the main path readable and the emit-pr chain unit-testable.
    """
    forge_repo_arg = getattr(args, "forge_repo", None) or os.environ.get("FORGE_REPO")
    if not forge_repo_arg:
        msg = (
            "--emit-pr requires --forge-repo PATH or the FORGE_REPO env var. "
            "Point it at a local clone of the forge repo."
        )
        if json_output:
            sys.stdout.write(json.dumps({"error": msg}) + "\n")
        else:
            sys.stderr.write(f"forge --harvest: {msg}\n")
        return _EXIT_EMIT_PR_PRECONDITION

    forge_repo = Path(forge_repo_arg).resolve()

    risk_filter_arg = getattr(args, "emit_pr_risk_filter", None)
    risk_filter: tuple[str, ...] = (
        tuple(s.strip() for s in str(risk_filter_arg).split(",") if s.strip())
        if risk_filter_arg
        else ("safe-apply",)
    )

    # ``emit_pr_mode`` is constrained to {"branch","github"} by the
    # parser's ``choices=`` declaration above (``"off"`` is filtered
    # out by the caller). ``cast`` narrows the static type without a
    # runtime check — the dynamic guard lives in ``_run_harvest``.
    mode_lit = cast(Literal["branch", "github"], emit_pr_mode)
    report = emit_pr(
        bundle,
        forge_repo,
        mode=mode_lit,
        risk_filter=risk_filter,
        pr_title=getattr(args, "pr_title", None),
        pr_body=getattr(args, "pr_body", None),
        quiet=quiet,
    )

    if json_output:
        sys.stdout.write(json.dumps(report.to_dict(), indent=2) + "\n")
    else:
        report.render_human(sys.stdout)

    telemetry.emit(
        telemetry.EVENT_EMIT_PR_RAN,
        project_root=bundle.project_root,
        mode=emit_pr_mode,
        branch=report.branch_name,
        pr_url=report.pr_url,
        entry_count=len(report.entries),
        accepted=report.committed,
        skipped=report.skipped,
        deferred=report.deferred,
        errored=report.errored,
    )

    if report.errors:
        return _EXIT_EMIT_PR_PRECONDITION
    return 0
