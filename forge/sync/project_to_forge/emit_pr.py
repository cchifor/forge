"""``forge --emit-pr`` — commit harvest candidates to a branch in ``$FORGE_REPO`` (Phase 6 close).

The final deferred verb of the Story B round-trip workflow. After
``forge --harvest`` produces a bundle, the user (or maintainer) needs
to land those candidates upstream. ``--emit-pr`` automates the
``git checkout -b harvest/<bundle_id>`` + per-candidate
``git commit`` (+ optional ``gh pr create``) so the harvest →
upstream-PR step doesn't require a manual recipe.

Modes:

* ``branch`` — create a local branch in the forge clone, commit each
  candidate atomically (one commit per fragment+kind pairing), and
  stop. The operator opens the PR by hand. Useful for offline
  workflows or for inspecting the commits before pushing.
* ``github`` — same as ``branch``, plus invoke ``gh pr create`` once
  the branch is built. Requires the ``gh`` CLI installed + authenticated;
  pre-condition failures surface in ``report.errors`` rather than
  raising.

Behavioural notes:

* The helper *never* pushes — it only operates on the local clone.
  Pushing is gated by the ``gh pr create`` invocation in ``github``
  mode, which handles its own remote push via the ``gh`` CLI.
* Each candidate gets its own commit so the upstream review can land
  / revert candidates independently. The commit subjects share a
  ``harvest(<fragment>): <kind>`` prefix so the resulting branch reads
  as a coherent series in ``git log --oneline``.
* The applier (:func:`apply_bundle_to_fragments`) is called
  one-candidate-at-a-time so any per-candidate failure (deferred /
  errored) gets surfaced in the emit report alongside its commit-or-
  not status. Skipped candidates (risk filtered, unchanged) don't
  produce commits.
* Pre-conditions (clean working tree, ``gh`` available) are validated
  up-front. Any failure produces a report with ``errors[]`` populated
  *before* any mutation — the forge_repo isn't touched.

Symmetric to :mod:`forge.sync.project_to_forge.accept`: the accept
verb closes Story B from the project side after the PR lands; this
verb opens the PR from the project side.
"""

from __future__ import annotations

import getpass
import os
import subprocess  # noqa: S404 — we intentionally shell out to git + gh, with cwd=forge_repo.
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Literal

from forge.sync.project_to_forge.apply_bundle import (
    ApplyBundleEntry,
    apply_bundle_to_fragments,
)
from forge.sync.project_to_forge.harvester import HarvestBundle

# Default risk-filter — only the auto-acceptable tier is committed to
# the branch. Pass an explicit filter to ``emit_pr`` to land needs-
# review candidates as well (rare; reviewers should know what they're
# doing).
_DEFAULT_RISK_FILTER: tuple[str, ...] = ("safe-apply",)

# Per-entry action vocabulary. ``committed`` is the success case; the
# rest are diagnostic and either flow through to the next iteration or
# (for branch-level errors) terminate the run.
EmitPrAction = Literal["committed", "skipped-unchanged", "deferred", "error", "skipped-risk"]
"""Per-entry action surfaced in :class:`EmitPrEntry`."""


@dataclass(frozen=True)
class EmitPrEntry:
    """One candidate's disposition after the emit step.

    Attributes:
        fragment: Fragment name (matches :attr:`CandidatePatch.fragment`).
        kind: Candidate kind (``"files"`` / ``"block"`` / ``"deps"`` /
            ``"env"``).
        commit_sha: Git SHA of the commit landing this candidate. ``None``
            when no commit was made (skip / defer / error path).
        files_touched: POSIX paths (relative to ``forge_repo``) the
            applier wrote. Empty tuple when no write happened.
        action: One of :data:`EmitPrAction`. ``committed`` is the
            success case; the rest are diagnostic.
        reason: Free-form note explaining a non-``committed`` outcome.
    """

    fragment: str
    kind: str
    commit_sha: str | None
    files_touched: tuple[str, ...]
    action: str
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        """JSON-serializable form for the CLI ``--json`` envelope."""
        out: dict[str, Any] = {
            "fragment": self.fragment,
            "kind": self.kind,
            "action": self.action,
            "files_touched": list(self.files_touched),
        }
        if self.commit_sha:
            out["commit_sha"] = self.commit_sha
        if self.reason:
            out["reason"] = self.reason
        return out


@dataclass(frozen=True)
class EmitPrReport:
    """Aggregate report from a single :func:`emit_pr` invocation.

    Attributes:
        bundle_id: ID of the bundle that drove this emit run. Empty
            string when the bundle didn't carry one (defensive — every
            real harvest stamps a non-empty id).
        forge_repo: Path of the local forge clone that was mutated.
        branch_name: ``harvest/<bundle_id>`` — the branch the helper
            created and committed to. Empty when a pre-condition failed
            and no branch was created.
        entries: Per-candidate dispositions in bundle order.
        pr_url: URL captured from ``gh pr create`` (``github`` mode only).
            Empty in ``branch`` mode, or when ``gh`` returned no usable
            URL.
        errors: Branch-level / pre-condition errors. Non-empty implies
            the helper bailed before (or during) commit work — the
            operator should fix the listed issues and re-run.
    """

    bundle_id: str
    forge_repo: Path
    branch_name: str
    entries: tuple[EmitPrEntry, ...] = field(default_factory=tuple)
    pr_url: str = ""
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def committed(self) -> int:
        return sum(1 for e in self.entries if e.action == "committed")

    @property
    def skipped(self) -> int:
        return sum(1 for e in self.entries if e.action in {"skipped-unchanged", "skipped-risk"})

    @property
    def deferred(self) -> int:
        return sum(1 for e in self.entries if e.action == "deferred")

    @property
    def errored(self) -> int:
        return sum(1 for e in self.entries if e.action == "error")

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable form for the CLI ``--json`` envelope."""
        return {
            "bundle_id": self.bundle_id,
            "forge_repo": str(self.forge_repo),
            "branch_name": self.branch_name,
            "committed": self.committed,
            "skipped": self.skipped,
            "deferred": self.deferred,
            "errored": self.errored,
            "pr_url": self.pr_url,
            "entries": [e.as_dict() for e in self.entries],
            "errors": list(self.errors),
        }

    def render_human(self, stream: IO[str]) -> None:
        """Render a one-line summary + per-entry sample to ``stream``.

        Caps per-entry output at 20 rows so a wide bundle doesn't flood
        the terminal — ``--json`` is the canonical channel for full
        inventories. Branch-level errors print first and short-circuit
        the rest of the rendering: there's nothing else useful to say.
        """
        if self.errors:
            stream.write(f"forge emit-pr: pre-condition error ({len(self.errors)})\n")
            for err in self.errors[:20]:
                stream.write(f"  ! {err}\n")
            return

        prefix = (
            f"forge emit-pr: committed={self.committed} skipped={self.skipped} "
            f"deferred={self.deferred} errored={self.errored} "
            f"(branch={self.branch_name or '<none>'})"
        )
        if self.pr_url:
            prefix += f" pr={self.pr_url}"
        stream.write(prefix + "\n")

        sample_cap = 20
        emitted = 0
        for entry in self.entries:
            if emitted >= sample_cap:
                break
            if entry.action in {"skipped-unchanged", "skipped-risk"}:
                # Quiet the routine no-ops in human mode; JSON keeps them.
                continue
            marker = {
                "committed": "+",
                "deferred": "~",
                "error": "!",
            }.get(entry.action, " ")
            sha = f" {entry.commit_sha[:8]}" if entry.commit_sha else ""
            note = f"  ({entry.reason})" if entry.reason else ""
            stream.write(f"  {marker}{sha} {entry.fragment}/{entry.kind} [{entry.action}]{note}\n")
            emitted += 1
        remaining = max(0, len(self.entries) - emitted)
        if remaining > sample_cap:
            stream.write(f"  ... and {remaining - sample_cap} more (use --json for full output)\n")


def emit_pr(
    bundle: HarvestBundle,
    forge_repo: Path,
    *,
    mode: Literal["branch", "github"] = "branch",
    risk_filter: tuple[str, ...] = _DEFAULT_RISK_FILTER,
    pr_title: str | None = None,
    pr_body: str | None = None,
    quiet: bool = False,
) -> EmitPrReport:
    """Commit harvest candidates to a fresh branch in ``forge_repo``.

    Behaviour:

    1. Validate ``forge_repo`` is a git working tree and clean.
       Pre-conditions fail fast with ``errors[]`` populated and *no*
       branch / commit work performed.
    2. Compute branch name: ``harvest/<bundle_id>``.
    3. ``git checkout -b <branch>`` from the current HEAD.
    4. For each candidate with ``risk in risk_filter``:

       * Apply it via :func:`apply_bundle_to_fragments` (called per
         candidate so per-candidate failures are isolated).
       * ``git add <touched files>`` (the applier reports them).
       * ``git commit -m "<scoped subject>"`` — one commit per
         fragment+kind+rel_path, never a mega-commit.

       Candidates filtered by ``risk_filter`` land as
       ``skipped-risk`` (recorded but not committed). Candidates the
       applier classifies ``deferred`` / ``errored`` produce the
       matching entry with no commit.
    5. When ``mode == "github"``: invoke ``gh pr create --title <title>
       --body <body>``. Capture the PR URL into the report.

    Args:
        bundle: The harvest bundle to apply + commit.
        forge_repo: Root of a local clone of the forge repo (the
            directory containing ``forge/__init__.py``).
        mode: ``"branch"`` to stop after committing; ``"github"`` to
            additionally open a PR via ``gh``.
        risk_filter: Risks the helper commits. Defaults to
            ``("safe-apply",)``.
        pr_title: Overrides the auto-generated title. ``github`` mode
            only; in ``branch`` mode the value is recorded but not
            surfaced.
        pr_body: Overrides the auto-generated body. ``github`` mode
            only.
        quiet: When ``False``, the underlying applier prints one line
            per candidate. The emit helper itself stays silent — the
            CLI dispatcher handles user-facing output.

    Returns:
        An :class:`EmitPrReport` describing what happened. Errors are
        captured rather than raised: the caller decides how to surface
        them.
    """
    bundle_id = bundle.bundle_id or "unknown"
    branch_name = f"harvest/{bundle_id}"

    # ----- Pre-conditions ----------------------------------------------------
    pre_errors = _validate_preconditions(forge_repo, mode=mode)
    if pre_errors:
        return EmitPrReport(
            bundle_id=bundle_id,
            forge_repo=forge_repo,
            branch_name="",
            entries=(),
            errors=tuple(pre_errors),
        )

    # ----- Branch creation ---------------------------------------------------
    branch_err = _create_branch(forge_repo, branch_name)
    if branch_err:
        return EmitPrReport(
            bundle_id=bundle_id,
            forge_repo=forge_repo,
            branch_name="",
            entries=(),
            errors=(branch_err,),
        )

    # ----- Per-candidate apply + commit -------------------------------------
    entries: list[EmitPrEntry] = []
    for cand in bundle.candidates:
        entry = _process_candidate(
            cand=cand,
            bundle=bundle,
            forge_repo=forge_repo,
            risk_filter=risk_filter,
            quiet=quiet,
        )
        entries.append(entry)

    # ----- gh pr create (github mode) ---------------------------------------
    pr_url = ""
    errors: list[str] = []
    if mode == "github":
        committed_any = any(e.action == "committed" for e in entries)
        if not committed_any:
            errors.append("no candidates committed; skipping gh pr create")
        else:
            url, gh_err = _create_pr(
                forge_repo=forge_repo,
                branch_name=branch_name,
                title=pr_title or _default_pr_title(bundle, entries),
                body=pr_body or _default_pr_body(bundle, entries, forge_repo=forge_repo),
            )
            if gh_err:
                errors.append(gh_err)
            else:
                pr_url = url

    return EmitPrReport(
        bundle_id=bundle_id,
        forge_repo=forge_repo,
        branch_name=branch_name,
        entries=tuple(entries),
        pr_url=pr_url,
        errors=tuple(errors),
    )


# ---------------------------------------------------------------------------
# Pre-conditions
# ---------------------------------------------------------------------------


def _validate_preconditions(forge_repo: Path, *, mode: str) -> list[str]:
    """Validate the forge_repo + (for github mode) the gh CLI.

    Returns a list of error strings. Empty list means OK.
    """
    errors: list[str] = []

    if not forge_repo.exists():
        errors.append(f"forge_repo does not exist: {forge_repo}")
        return errors
    if not forge_repo.is_dir():
        errors.append(f"forge_repo is not a directory: {forge_repo}")
        return errors
    if not (forge_repo / ".git").exists():
        errors.append(f"forge_repo is not a git working tree: {forge_repo}")
        return errors

    # Clean working tree check. ``git status --porcelain`` prints one
    # line per dirty path; empty output means clean. We deliberately
    # don't honour untracked files differently — any dirt is a refusal
    # signal, because mixing a harvest commit into unrelated work
    # produces an unreviewable PR.
    rc, out, err = _run_git(forge_repo, ["status", "--porcelain"])
    if rc != 0:
        errors.append(f"git status failed in {forge_repo}: {err.strip() or out.strip()}")
        return errors
    if out.strip():
        dirty = out.strip().splitlines()
        sample = ", ".join(line[3:] for line in dirty[:3])
        more = f" (+{len(dirty) - 3} more)" if len(dirty) > 3 else ""
        errors.append(
            f"forge_repo has uncommitted changes; refusing to mutate. Clean first ({sample}{more})"
        )

    if mode == "github":
        # ``gh --version`` is the cheap installed-check. ``gh auth
        # status`` confirms credentials — split into two probes so the
        # error message can pinpoint which condition failed.
        rc, out, err = _run_gh(forge_repo, ["--version"])
        if rc != 0:
            errors.append(
                "mode='github' requires the 'gh' CLI on PATH; install from https://cli.github.com/"
            )
        else:
            rc, out, err = _run_gh(forge_repo, ["auth", "status"])
            if rc != 0:
                errors.append(
                    "mode='github' requires 'gh auth login'; run it first and re-run emit-pr"
                )

    return errors


def _create_branch(forge_repo: Path, branch_name: str) -> str | None:
    """Create + checkout the harvest branch. Returns error message or None."""
    rc, out, err = _run_git(forge_repo, ["checkout", "-b", branch_name])
    if rc != 0:
        msg = (err or out).strip()
        # The most common failure mode is "branch already exists" — the
        # operator re-ran emit-pr on the same bundle. Surface a clear
        # error so the next step is obvious.
        if "already exists" in msg:
            return (
                f"branch {branch_name!r} already exists in {forge_repo}; "
                f"delete it (git branch -D {branch_name}) or run on a fresh bundle"
            )
        return f"git checkout -b {branch_name} failed: {msg}"
    return None


# ---------------------------------------------------------------------------
# Per-candidate processing
# ---------------------------------------------------------------------------


def _process_candidate(
    *,
    cand: Any,
    bundle: HarvestBundle,
    forge_repo: Path,
    risk_filter: tuple[str, ...],
    quiet: bool,
) -> EmitPrEntry:
    """Apply + commit one candidate. Returns the dispositional entry."""
    if cand.risk not in risk_filter:
        return EmitPrEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            commit_sha=None,
            files_touched=(),
            action="skipped-risk",
            reason=f"risk={cand.risk!r} not in filter {risk_filter!r}",
        )

    # Build a single-candidate sub-bundle so apply_bundle_to_fragments
    # runs the per-kind branch we want without touching the rest of the
    # bundle. We deep-copy via dataclass replace to keep the original
    # bundle intact — callers may reuse it across calls.
    sub_bundle = replace(bundle, candidates=[cand])
    apply_report = apply_bundle_to_fragments(
        sub_bundle,
        forge_repo,
        risk_filter=risk_filter,
        quiet=quiet,
    )
    apply_entry: ApplyBundleEntry | None = apply_report.entries[0] if apply_report.entries else None
    if apply_entry is None:
        # apply_bundle_to_fragments always emits one entry per candidate
        # — an empty entries list is a contract violation we should
        # surface rather than silently drop.
        return EmitPrEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            commit_sha=None,
            files_touched=(),
            action="error",
            reason="applier returned no entry (internal contract violation)",
        )

    if apply_entry.status == "deferred":
        return EmitPrEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            commit_sha=None,
            files_touched=(),
            action="deferred",
            reason=apply_entry.error or "applier deferred (unsupported / non-literal)",
        )
    if apply_entry.status == "errored":
        return EmitPrEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            commit_sha=None,
            files_touched=(),
            action="error",
            reason=apply_entry.error or "applier errored",
        )
    if apply_entry.status == "skipped":
        return EmitPrEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            commit_sha=None,
            files_touched=(),
            action="skipped-risk",
            reason=apply_entry.error or "risk filter mismatch",
        )

    # status in {"applied", "skipped-unchanged"} — both arrive here.
    # ``skipped-unchanged`` means the applier saw a no-op write, so we
    # don't have a meaningful commit to produce. Capture the no-op for
    # the report and move on.
    if apply_entry.status == "skipped-unchanged":
        return EmitPrEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            commit_sha=None,
            files_touched=(),
            action="skipped-unchanged",
            reason="applier reported no change on disk",
        )

    # The applier wrote at least one file. Figure out which paths
    # changed by querying ``git status --porcelain`` — the applier's
    # ``entry.target`` is a strong hint but the safer move is to
    # ask git directly so we catch any side-effect writes (e.g.
    # ``inject.yaml`` rewrites that touch multiple lines but report a
    # single target).
    rc, out, err = _run_git(forge_repo, ["status", "--porcelain"])
    if rc != 0:
        return EmitPrEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            commit_sha=None,
            files_touched=(),
            action="error",
            reason=f"git status post-apply failed: {(err or out).strip()}",
        )
    touched = _parse_porcelain_paths(out)
    if not touched:
        # Applier said applied but git sees no delta. Likely a write of
        # identical bytes — record as unchanged so the report stays
        # honest.
        return EmitPrEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            commit_sha=None,
            files_touched=(),
            action="skipped-unchanged",
            reason="applier wrote identical bytes; no git delta",
        )

    rc, out, err = _run_git(forge_repo, ["add", "--", *touched])
    if rc != 0:
        return EmitPrEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            commit_sha=None,
            files_touched=tuple(touched),
            action="error",
            reason=f"git add failed: {(err or out).strip()}",
        )

    subject = _commit_subject(cand)
    body = _commit_body(cand, bundle)
    message = f"{subject}\n\n{body}\n" if body else f"{subject}\n"
    rc, out, err = _run_git(forge_repo, ["commit", "-m", message])
    if rc != 0:
        return EmitPrEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            commit_sha=None,
            files_touched=tuple(touched),
            action="error",
            reason=f"git commit failed: {(err or out).strip()}",
        )

    rc, sha_out, err = _run_git(forge_repo, ["rev-parse", "HEAD"])
    sha = sha_out.strip() if rc == 0 else ""
    return EmitPrEntry(
        fragment=cand.fragment,
        kind=cand.kind,
        commit_sha=sha or None,
        files_touched=tuple(touched),
        action="committed",
    )


def _parse_porcelain_paths(out: str) -> list[str]:
    """Extract file paths from ``git status --porcelain`` output.

    Porcelain v1 format: ``XY path`` per line, where X and Y are
    status code letters (or ``?`` for untracked). Rename entries (R)
    use ``XY old -> new`` — we keep both halves to be safe.
    """
    paths: list[str] = []
    for raw_line in out.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        # Skip the two-char status prefix and the separator space.
        rest = line[3:] if len(line) > 3 else line
        if " -> " in rest:
            old, new = rest.split(" -> ", 1)
            paths.extend([old.strip(), new.strip()])
        else:
            paths.append(rest.strip())
    return [p for p in paths if p]


# ---------------------------------------------------------------------------
# Commit + PR message templates
# ---------------------------------------------------------------------------


def _commit_subject(cand: Any) -> str:
    """One-line commit subject for a single candidate.

    Format: ``harvest(<fragment>): <kind> <rel_path>``. Keeps the
    fragment name in the scope so ``git log --oneline`` reads as a
    coherent series even when the branch covers multiple fragments.
    """
    rel = cand.rel_path or "<unknown>"
    return f"harvest({cand.fragment}): {cand.kind} {rel}"


def _commit_body(cand: Any, bundle: HarvestBundle) -> str:
    """Multi-line commit body referencing the bundle + candidate metadata.

    Carries the bundle id (so reviewers can find the originating
    harvest), the risk classification (so a needs-review commit isn't
    silently elevated), and the rationale (extractor's note on
    classification).
    """
    lines = [
        f"Bundle: {bundle.bundle_id}",
        f"Risk: {cand.risk}",
    ]
    if cand.rationale:
        lines.append(f"Rationale: {cand.rationale}")
    if cand.backend and cand.backend != "project":
        lines.append(f"Backend: {cand.backend}")
    return "\n".join(lines)


def _default_pr_title(bundle: HarvestBundle, entries: Iterable[EmitPrEntry]) -> str:
    """Auto-generate the PR title from the bundle + emitted entries.

    Format: ``Harvest from <project_name>: <comma-list-of-fragments>``.
    Caps the fragment list at 5 names to keep titles under GitHub's
    256-char limit; bundles covering more fragments get an ``(+N more)``
    suffix.
    """
    project_name = bundle.project_root.name or "project"
    committed = [e for e in entries if e.action == "committed"]
    fragments = sorted({e.fragment for e in committed})
    if not fragments:
        fragments = sorted({c.fragment for c in bundle.candidates})
    head = fragments[:5]
    tail_count = max(0, len(fragments) - len(head))
    list_part = ", ".join(head) if head else "no candidates"
    if tail_count:
        list_part += f" (+{tail_count} more)"
    return f"Harvest from {project_name}: {list_part}"


def _default_pr_body(
    bundle: HarvestBundle,
    entries: Iterable[EmitPrEntry],
    *,
    forge_repo: Path | None = None,
) -> str:
    """Auto-generate the PR body from the bundle + emitted entries.

    The body carries the originating project + harvest timestamp, the
    per-candidate inventory (so reviewers can spot-check anything
    flagged ``needs-review``), and a brief reviewer checklist anchored
    to the round-trip contract.

    ``forge_repo`` (optional) is used to look up ``git config user.email``
    for the author line; falls back to the local user id when unset.
    """
    committed = [e for e in entries if e.action == "committed"]
    author = _git_author_email(forge_repo) or _user_id()
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = [
        f"Harvested by {author} from {bundle.project_root} on {timestamp}.",
        f"Bundle ID: {bundle.bundle_id}",
        f"Forge version: {bundle.forge_version}",
        "",
        "Candidates in this PR (risk=safe-apply unless noted):",
    ]
    if committed:
        # Map each committed entry back to the originating candidate
        # so we can surface the rel_path + risk in the body.
        cand_by_key = {(c.fragment, c.kind, c.rel_path): c for c in bundle.candidates}
        for entry in committed:
            cand = None
            for key, c in cand_by_key.items():
                if key[0] == entry.fragment and key[1] == entry.kind:
                    cand = c
                    break
            risk_tag = "" if (cand is None or cand.risk == "safe-apply") else f" [{cand.risk}]"
            rel = cand.rel_path if cand is not None else ""
            sep = " @ " if rel else ""
            lines.append(f"  - {entry.fragment}/{entry.kind}{sep}{rel}{risk_tag}")
    else:
        lines.append(
            "  (no committed candidates — see entries[] in the bundle for skipped/deferred)"
        )

    lines.extend(
        [
            "",
            "Reviewer checklist:",
            "  - [ ] applies cleanly to forge HEAD",
            "  - [ ] tests/matrix round-trip lane passes",
            "  - [ ] doesn't regress other-language parity",
            "",
            "Generated by `forge --emit-pr` — see docs/round-trip.md (Story B).",
        ]
    )
    return "\n".join(lines)


def _git_author_email(forge_repo: Path | None) -> str:
    """Best-effort lookup of ``git config user.email`` for the PR body."""
    if forge_repo is None:
        return ""
    rc, out, _ = _run_git(forge_repo, ["config", "--get", "user.email"])
    if rc == 0:
        return out.strip()
    return ""


def _user_id() -> str:
    """Last-resort author identifier for the PR body."""
    try:
        return getpass.getuser() or "unknown"
    except OSError:
        return os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


# ---------------------------------------------------------------------------
# gh pr create
# ---------------------------------------------------------------------------


def _create_pr(
    *,
    forge_repo: Path,
    branch_name: str,
    title: str,
    body: str,
) -> tuple[str, str | None]:
    """Run ``gh pr create`` and return ``(pr_url, error_or_None)``.

    The branch must already exist locally (``--head`` defaults to the
    current branch). We DO NOT push from this helper; ``gh pr create``
    will push if needed, depending on the user's git config (default
    branch tracking). The CLI behaviour means a brand-new branch lands
    a remote push as part of opening the PR.
    """
    args = [
        "pr",
        "create",
        "--title",
        title,
        "--body",
        body,
        "--head",
        branch_name,
    ]
    rc, out, err = _run_gh(forge_repo, args)
    if rc != 0:
        return "", f"gh pr create failed: {(err or out).strip()}"
    # ``gh pr create`` prints the PR URL on the last non-empty line of
    # stdout. Parse defensively — some gh versions print extra lines
    # (e.g. "Creating pull request for ...").
    pr_url = ""
    for raw_line in reversed(out.splitlines()):
        line = raw_line.strip()
        if line.startswith("http://") or line.startswith("https://"):
            pr_url = line
            break
    return pr_url, None


# ---------------------------------------------------------------------------
# Subprocess plumbing
# ---------------------------------------------------------------------------


def _run_git(
    forge_repo: Path,
    args: list[str],
) -> tuple[int, str, str]:
    """Run ``git`` with ``cwd=forge_repo`` and return (rc, stdout, stderr)."""
    return _run_subprocess(["git", *args], cwd=forge_repo)


def _run_gh(
    forge_repo: Path,
    args: list[str],
) -> tuple[int, str, str]:
    """Run ``gh`` with ``cwd=forge_repo`` and return (rc, stdout, stderr)."""
    return _run_subprocess(["gh", *args], cwd=forge_repo)


def _run_subprocess(
    cmd: list[str],
    *,
    cwd: Path,
) -> tuple[int, str, str]:
    """Common subprocess runner. Captures stdout + stderr as text.

    Tests can monkeypatch this single entry point (``emit_pr._run_subprocess``)
    to stub the git + gh invocations without a PATH-stub dance.
    """
    try:
        completed = subprocess.run(  # noqa: S603 — cmd is built from literal lists; no shell.
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as e:
        # ``git`` / ``gh`` not on PATH — surface as rc=127 with the
        # underlying error so callers don't have to introspect
        # exceptions.
        return 127, "", str(e)
    return completed.returncode, completed.stdout, completed.stderr
