"""Apply harvest-bundle candidates back to the forge fragment tree (Phase 5/6).

The forward direction (``forge --update`` →
:func:`forge.sync.forge_to_project.updater.update_project`) re-applies
fragment intent into a generated project. The reverse direction
(``forge --harvest`` →
:func:`forge.sync.project_to_forge.harvester.harvest_project`) extracts
user edits as candidate fragment patches. This module closes the loop:
given a :class:`HarvestBundle`, write the user edits back into the
fragment source tree so a subsequent ``forge --update`` (or a fresh
``forge --generate``) would re-emit the user's text.

Supported candidate kinds:
  * ``kind="files"`` → overwrite ``<fragment_dir>/<lang>/files/<rel>``
    with the candidate's current content.
  * ``kind="block"`` → rewrite the matching ``inject.yaml`` entry's
    ``snippet:`` field with :attr:`CandidatePatch.current_body`. The
    YAML is fully re-serialised via :mod:`yaml.safe_dump` so the
    formatting may shift (block-literals collapse, comments at the
    file head are preserved by a manual prepend, mid-list comments
    are NOT preserved — see :func:`_rewrite_inject_yaml_snippet` for
    the contract). The fragment's authors keep the high-signal
    structure; formatting drift is the trade-off for an automated
    apply-back path.
  * ``kind="deps"`` / ``kind="env"`` → rewrite the appropriate
    ``FragmentImplSpec(...).dependencies=(...)`` /
    ``env_vars=((...),)`` tuple inside the fragment-registering
    ``fragments.py`` module. The applier walks
    ``forge/features/*/fragments.py`` (and any other location the
    fragment registers from) to find the matching
    ``register_fragment(Fragment(name="<name>", ...))`` call, then
    locates the ``FragmentImplSpec(...)`` block for the right
    backend language and mutates the literal tuple in-place via
    text substitution. The substitution preserves the surrounding
    formatting (indentation, comments outside the tuple, trailing
    commas) but assumes the tuple is a Python literal. When the
    expression is non-literal (e.g.
    ``dependencies=base_deps + ("extra",)`` or
    ``dependencies=Fragment.python_deps()``) the applier falls back
    to ``deferred`` so the operator can apply the change by hand.
    See :func:`_rewrite_fragment_deps` and
    :func:`_rewrite_fragment_env_vars` for the contract.

The contract is intentionally narrow: ``apply_bundle_to_fragments`` is
the substrate that ``forge --harvest --accept`` (a Phase 6 CLI verb)
will sit on top of, plus the dependency the round-trip CI lane uses to
exercise the full forward→reverse→apply→forward cycle in tests.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from forge.config import BackendLanguage
from forge.fragments import FRAGMENT_REGISTRY

if TYPE_CHECKING:
    from forge.extractors.pipeline import CandidatePatch
    from forge.fragments import Fragment, FragmentImplSpec
    from forge.sync.project_to_forge.harvester import HarvestBundle


# Risk classifications the bundle applier acts on by default. Mirrors
# the CLI's ``--accept-harvested`` default surface. Operators wanting
# to override this for a one-off review pass pass an explicit
# ``risk_filter`` to :func:`apply_bundle_to_fragments`.
_DEFAULT_RISK_FILTER: tuple[str, ...] = ("safe-apply",)


@dataclass(frozen=True)
class ApplyBundleEntry:
    """One candidate's resolution after running the apply step.

    Attributes:
        fragment: Fragment name (matches :attr:`CandidatePatch.fragment`).
        kind: Candidate kind (``"files"`` / ``"block"`` / ``"deps"`` /
            ``"env"`` / ``"cross-lang-suggest"``).
        rel_path: POSIX rel-path identifying the patch target inside the
            fragment tree (or the project tree, for ``"block"`` /
            ``"deps"`` / ``"env"``).
        status: One of ``"applied"`` (write succeeded), ``"skipped"``
            (filtered out by ``risk_filter``),
            ``"skipped-unchanged"`` (idempotent re-run — the change
            was already in the fragment source on disk),
            ``"deferred"`` (kind not supported in v1, non-literal
            expression that needs a manual edit, or RFC-006
            ``cross-lang-suggest`` informational entry — see module
            docstring), or ``"errored"`` (apply attempted but failed;
            see :attr:`error`).
        target: Absolute path on disk that was (or would have been)
            written. ``None`` for ``"skipped"`` / ``"deferred"`` /
            ``"errored"`` entries that didn't resolve a fragment path.
        error: Free-form error message for ``"errored"`` entries. Empty
            for the others.
    """

    fragment: str
    kind: str
    rel_path: str
    status: str
    target: str | None = None
    error: str = ""


@dataclass(frozen=True)
class ApplyBundleReport:
    """Aggregate report from a :func:`apply_bundle_to_fragments` run.

    Attributes:
        entries: Per-candidate disposition. Order matches the bundle's
            ``candidates`` list so reviewers can correlate entries
            against the harvest manifest.
        applied: Count of candidates the applier wrote successfully.
        skipped: Count of candidates filtered out by ``risk_filter`` or
            by candidate-level filters (binary files, sentinel-corrupt
            blocks).
        deferred: Count of candidates whose ``kind`` is not yet
            supported (``"deps"`` / ``"env"`` in v1.2;
            ``"block"`` graduated to ``applied`` in this phase).
        errored: Count of candidates the applier attempted to write but
            failed on (permission denied, missing fragment dir, etc.).
    """

    entries: list[ApplyBundleEntry] = field(default_factory=list)
    applied: int = 0
    skipped: int = 0
    deferred: int = 0
    errored: int = 0


def apply_bundle_to_fragments(
    bundle: HarvestBundle,
    forge_repo: Path,
    *,
    risk_filter: tuple[str, ...] = _DEFAULT_RISK_FILTER,
    quiet: bool = False,
) -> ApplyBundleReport:
    """Apply a harvest bundle's candidates back to the forge source tree.

    For each candidate with ``risk in risk_filter``:
      * ``kind="files"`` → overwrite the fragment-shipped file at
        ``<fragment_dir>/<lang>/files/<rel>`` with the candidate's
        current on-disk content (read from
        :attr:`CandidatePatch.target_path`). When the fragment doesn't
        ship a ``files/`` entry at that rel-path we still write it —
        the user-added file is now part of the fragment.
      * ``kind="block"`` → rewrite the matching
        ``<fragment_dir>/inject.yaml`` entry's ``snippet:`` field with
        :attr:`CandidatePatch.current_body`. Matched by
        ``(target_path, feature_key, marker)`` against the YAML's
        entries. The YAML is re-serialised wholesale — comments
        embedded between entries are NOT preserved (the trade-off
        documented at module level). Leading file comments survive
        via a manual prepend.
      * ``kind="deps"`` → rewrite the
        ``FragmentImplSpec(...).dependencies=(...)`` tuple inside
        the fragment-registering ``fragments.py`` module. The
        candidate's ``diff`` payload is a small JSON describing the
        ``action`` (``"added"`` / ``"removed"`` / ``"modified"``),
        the dep ``name``, the ``fragment_spec`` (pre-edit), and the
        ``project_spec`` (post-edit). The language is inferred from
        :attr:`CandidatePatch.rel_path` (``pyproject.toml`` →
        Python, ``package.json`` → Node, ``Cargo.toml`` → Rust).
        Non-literal tuple expressions land as ``deferred``.
      * ``kind="env"`` → rewrite the
        ``FragmentImplSpec(...).env_vars=((...),)`` tuple-of-tuples
        on every language impl the fragment declares the var in
        (env vars are conventionally shared across the per-language
        impls of a fragment). Diff payload mirrors deps but with
        ``key``, ``fragment_value``, ``project_value``. Non-literal
        tuple expressions land as ``deferred``.

    Args:
        bundle: The harvest bundle to apply. Typically the result of a
            preceding :func:`harvest_project` call.
        forge_repo: Root of the forge source tree (the directory that
            contains ``forge/__init__.py``). The fragments under
            ``forge/templates/_fragments/`` and ``forge/features/`` are
            both honoured — the helper relies on the registry's
            ``impl.fragment_dir`` lookup to find the canonical location.
        risk_filter: Subset of the candidate-risk vocabulary the helper
            will act on. Defaults to ``("safe-apply",)`` — the
            auto-acceptable tier. Pass ``("safe-apply", "needs-review")``
            to land needs-review candidates as well (rare; the operator
            should know what they're doing).
        quiet: When ``False``, prints a one-line per-candidate progress
            note. Tests should pass ``True``.

    Returns:
        An :class:`ApplyBundleReport` with per-candidate dispositions
        and aggregate counts.

    The helper never raises on individual candidate failures — it
    records the error in the report and continues. The caller can
    inspect ``report.errored`` and the matching entries to decide how to
    surface the partial-failure case.
    """
    entries: list[ApplyBundleEntry] = []
    applied = 0
    skipped = 0
    deferred = 0
    errored = 0

    for cand in bundle.candidates:
        # Filter by risk. Skipped candidates are still recorded so the
        # report shows the reviewer "we saw this; here's why we didn't
        # apply it" — preferable to silent drop.
        if cand.risk not in risk_filter:
            entries.append(
                ApplyBundleEntry(
                    fragment=cand.fragment,
                    kind=cand.kind,
                    rel_path=cand.rel_path,
                    status="skipped",
                    error=f"risk={cand.risk!r} not in filter {risk_filter!r}",
                )
            )
            skipped += 1
            continue

        if cand.kind == "files":
            entry = _apply_files_candidate(cand, forge_repo=forge_repo, quiet=quiet)
        elif cand.kind == "block":
            entry = _apply_block_candidate(cand, forge_repo=forge_repo, quiet=quiet)
        elif cand.kind == "deps":
            entry = _apply_deps_candidate(cand, forge_repo=forge_repo, quiet=quiet)
        elif cand.kind == "env":
            entry = _apply_env_candidate(cand, forge_repo=forge_repo, quiet=quiet)
        elif cand.kind == "cross-lang-suggest":
            # RFC-006 cross-language parity hint — never applied
            # automatically. The candidate carries the path of a
            # sibling-language impl that the maintainer should mirror
            # by hand. emit-pr surfaces these in the reviewer
            # checklist; apply-back records the deferral so the
            # operator's report stays honest.
            entry = ApplyBundleEntry(
                fragment=cand.fragment,
                kind=cand.kind,
                rel_path=cand.rel_path,
                target=cand.target_path or None,
                status="deferred",
                error="cross-lang suggestion; apply manually to the named impl",
            )
        else:
            # Unknown kind — record + continue rather than crash. The
            # operator's harvest tooling and the apply lane must agree
            # on the kind vocabulary; a mismatch is a bug worth
            # surfacing.
            entry = ApplyBundleEntry(
                fragment=cand.fragment,
                kind=cand.kind,
                rel_path=cand.rel_path,
                status="errored",
                error=f"unknown candidate kind {cand.kind!r}",
            )

        entries.append(entry)
        if entry.status == "applied":
            applied += 1
        elif entry.status == "deferred":
            deferred += 1
        elif entry.status == "errored":
            errored += 1
        elif entry.status.startswith("skipped"):
            skipped += 1

    if not quiet:
        print(
            f"  [apply-bundle] applied={applied} skipped={skipped} "
            f"deferred={deferred} errored={errored}"
        )

    return ApplyBundleReport(
        entries=entries,
        applied=applied,
        skipped=skipped,
        deferred=deferred,
        errored=errored,
    )


# ---------------------------------------------------------------------------
# Per-kind appliers
# ---------------------------------------------------------------------------


def _apply_files_candidate(
    cand: CandidatePatch,
    *,
    forge_repo: Path,
    quiet: bool,
) -> ApplyBundleEntry:
    """Apply a ``kind="files"`` candidate to the fragment tree.

    Resolves the fragment's ``files/`` directory via the registry, then
    writes the candidate's current on-disk content (read from
    ``cand.target_path``) into ``<files_dir>/<cand.rel_path>``.

    Errors are captured as ``errored`` entries — the apply step is best-
    effort, never raising past the caller. Returns the disposition
    entry; the caller aggregates counts.
    """
    # Locate the fragment in the registry. A bundle whose fragments
    # aren't registered (plugin disabled, fragment removed) is a
    # config-time error — surface it but keep going.
    fragment = FRAGMENT_REGISTRY.get(cand.fragment)
    if fragment is None:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"fragment {cand.fragment!r} not in registry",
        )

    # The candidate carries a ``backend`` label (e.g. ``api``); the
    # registry indexes implementations by :class:`BackendLanguage`.
    # We don't have the language directly, so try every registered impl
    # and pick the one whose ``files_dir`` actually contains the
    # candidate's rel_path (or — for new fragment files — pick the
    # first impl that exists). This handles the multi-backend case
    # cleanly: a single fragment with python+node+rust implementations
    # picks the right one without requiring the bundle to record the
    # backend language explicitly.
    impl = _resolve_impl_for_candidate(fragment, cand)
    if impl is None:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"fragment {cand.fragment!r} has no implementation for backend {cand.backend!r}",
        )

    # Resolve the fragment dir against the supplied forge_repo so the
    # apply lands in the operator's chosen tree (typically a tmp_path
    # clone of the source so tests don't mutate the real fragments).
    fragment_dir = _resolve_fragment_dir_under(
        forge_repo=forge_repo,
        fragment_dir_str=impl.fragment_dir,
    )
    if fragment_dir is None or not fragment_dir.is_dir():
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"fragment dir not found under forge_repo: {impl.fragment_dir}",
        )

    files_dir = fragment_dir / "files"
    target = files_dir / cand.rel_path

    # Read the current content from the project. ``target_path`` is
    # absolute (the harvester stamps it). If the file disappeared
    # between harvest and apply, surface as errored — the bundle is
    # stale.
    source = Path(cand.target_path)
    if not source.is_file():
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            target=str(target),
            error=f"source file gone since harvest: {source}",
        )

    try:
        # ``read_bytes`` + ``write_bytes`` preserves the user's chosen
        # line endings. We deliberately don't normalize on write — the
        # next ``forge --generate`` re-emits the file, and any LF/CRLF
        # difference vs. the user's edit is exactly what the round-trip
        # contract should preserve.
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    except OSError as e:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            target=str(target),
            error=f"write failed: {e}",
        )

    if not quiet:
        print(f"  [apply-bundle] {cand.fragment}/{cand.rel_path} → {target}")

    return ApplyBundleEntry(
        fragment=cand.fragment,
        kind=cand.kind,
        rel_path=cand.rel_path,
        status="applied",
        target=str(target),
    )


def _apply_block_candidate(
    cand: CandidatePatch,
    *,
    forge_repo: Path,
    quiet: bool,
) -> ApplyBundleEntry:
    """Apply a ``kind="block"`` candidate to the fragment's inject.yaml.

    Locates the fragment's ``inject.yaml``, finds the entry whose
    ``target`` + ``marker`` match the candidate, and rewrites that
    entry's ``snippet:`` field with :attr:`CandidatePatch.current_body`.

    Match strategy:
      1. The fragment is resolved through :data:`FRAGMENT_REGISTRY`.
      2. Among the fragment's impls, we pick whichever one carries an
         ``inject.yaml`` containing an entry with the candidate's
         ``target`` and ``marker``. This lets one fragment with
         multiple language impls (rare for blocks today, but legal)
         route the back-port to the correct language.
      3. The matching YAML entry's snippet is rewritten in place; the
         file is fully re-serialised via :mod:`yaml.safe_dump`.

    Constraints + trade-offs:
      * ``current_body`` MUST be non-empty for a meaningful apply —
        an empty current body means "the user wiped the block" and
        we can't distinguish that from "an extractor that didn't
        populate the new field". Empty bodies surface as ``errored``.
      * Inline comments mid-list are NOT preserved by safe_dump. The
        file's leading comment block (everything up to the first
        non-comment/blank line) is preserved by reading the head and
        prepending it back. Per-entry comments are lost — this is the
        documented trade-off.
      * The match must be EXACT on (target, marker). A candidate that
        can't find its entry in ANY of the fragment's impls' inject.
        yaml files surfaces as ``errored`` — the harvest record points
        at something the fragment no longer ships, which the operator
        needs to know.
    """
    if not cand.current_body:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=(
                "block candidate has empty current_body; cannot rewrite "
                "inject.yaml snippet without the post-edit body"
            ),
        )
    if not cand.marker:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=(
                "block candidate missing marker field; cannot pin the inject.yaml entry to rewrite"
            ),
        )

    fragment = FRAGMENT_REGISTRY.get(cand.fragment)
    if fragment is None:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"fragment {cand.fragment!r} not in registry",
        )

    impl, fragment_dir, inject_yaml_path = _resolve_inject_yaml_for_block(
        fragment, cand, forge_repo=forge_repo
    )
    if impl is None or fragment_dir is None or inject_yaml_path is None:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=(
                f"no inject.yaml entry matches target={cand.rel_path!r} "
                f"marker={cand.marker!r} on fragment {cand.fragment!r}; "
                f"fragment may no longer ship this block"
            ),
        )

    try:
        rewrote = _rewrite_inject_yaml_snippet(
            inject_yaml_path=inject_yaml_path,
            target=cand.rel_path,
            marker=cand.marker,
            new_snippet=cand.current_body,
        )
    except OSError as e:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            target=str(inject_yaml_path),
            error=f"write failed: {e}",
        )
    if not rewrote:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            target=str(inject_yaml_path),
            error=(
                f"matching entry not found in {inject_yaml_path} for "
                f"target={cand.rel_path!r} marker={cand.marker!r}"
            ),
        )

    if not quiet:
        print(
            f"  [apply-bundle] {cand.fragment}/{cand.rel_path}#{cand.marker} → {inject_yaml_path}"
        )
    return ApplyBundleEntry(
        fragment=cand.fragment,
        kind=cand.kind,
        rel_path=cand.rel_path,
        status="applied",
        target=str(inject_yaml_path),
    )


def _resolve_inject_yaml_for_block(
    fragment: Fragment,
    cand: CandidatePatch,
    *,
    forge_repo: Path,
) -> tuple[FragmentImplSpec | None, Path | None, Path | None]:
    """Find the impl + inject.yaml path whose entry matches the candidate.

    Walks the fragment's impls in iteration order; for each, resolves
    the fragment_dir under ``forge_repo`` and parses any ``inject.yaml``
    present. Returns the first ``(impl, fragment_dir, inject_yaml)``
    triple whose YAML contains an entry with the candidate's
    ``(target, marker)``. Returns ``(None, None, None)`` when no impl
    matches.

    The lookup is read-only — we don't mutate the YAML here. The
    rewrite happens in :func:`_rewrite_inject_yaml_snippet` once the
    caller has confirmed which file to edit.
    """
    impls = fragment.implementations
    if not impls:
        return None, None, None

    for impl in impls.values():
        fragment_dir = _resolve_fragment_dir_under(
            forge_repo=forge_repo,
            fragment_dir_str=impl.fragment_dir,
        )
        if fragment_dir is None or not fragment_dir.is_dir():
            continue
        inject_yaml = fragment_dir / "inject.yaml"
        if not inject_yaml.is_file():
            continue
        try:
            doc = yaml.safe_load(inject_yaml.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(doc, list):
            continue
        for entry in doc:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("target", "")) != cand.rel_path:
                continue
            if str(entry.get("marker", "")) != cand.marker:
                continue
            return impl, fragment_dir, inject_yaml
    return None, None, None


def _rewrite_inject_yaml_snippet(
    *,
    inject_yaml_path: Path,
    target: str,
    marker: str,
    new_snippet: str,
) -> bool:
    """Rewrite the matching entry's ``snippet:`` field in ``inject_yaml_path``.

    Returns ``True`` when an entry was rewritten + the file was
    persisted; ``False`` when no entry matched (caller surfaces as
    ``errored``).

    Formatting contract (the trade-off documented at module level):
      * The leading comment block of the file (every consecutive line
        starting with ``#`` or empty, from the start of the file) is
        preserved verbatim by manual prepend.
      * Everything else is re-serialised via :mod:`yaml.safe_dump`
        with block-style output and ``allow_unicode=True``. Per-entry
        mid-list comments are lost. Block-literal snippets (``|`` /
        ``|-``) collapse to whatever safe_dump deems best — typically
        a ``|`` literal when the snippet contains newlines, or a
        plain string for single-line snippets.
      * Trailing newline is appended to match the original file's
        convention (every inject.yaml in the tree ends with one).
    """
    raw = inject_yaml_path.read_text(encoding="utf-8")
    doc = yaml.safe_load(raw)
    if not isinstance(doc, list):
        return False

    found = False
    for entry in doc:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("target", "")) != target:
            continue
        if str(entry.get("marker", "")) != marker:
            continue
        entry["snippet"] = new_snippet
        found = True
        break

    if not found:
        return False

    header = _extract_leading_comments(raw)
    body = yaml.safe_dump(
        doc,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=1_000_000,  # keep long snippets on one line when single-line
    )
    out = header + body
    if not out.endswith("\n"):
        out += "\n"
    inject_yaml_path.write_text(out, encoding="utf-8")
    return True


def _extract_leading_comments(raw: str) -> str:
    """Return the contiguous block of ``#``-comments + blanks at file start.

    Stops at the first line that's neither a comment nor blank. The
    returned string includes the trailing newline of the last comment
    line so the YAML body can be appended without joining onto a
    comment line.
    """
    lines = raw.splitlines(keepends=True)
    head: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            head.append(line)
            continue
        break
    return "".join(head)


def _resolve_impl_for_candidate(
    fragment: Fragment, cand: CandidatePatch
) -> FragmentImplSpec | None:
    """Pick the fragment impl whose ``files/`` tree carries ``cand.rel_path``.

    The harvester records a ``backend`` label (``api`` / ``project``)
    on the candidate but not the underlying ``BackendLanguage``, so we
    can't index ``fragment.implementations`` directly. Instead, we
    enumerate the available impls and prefer one whose ``files/``
    subtree already contains the rel-path on disk. Failing that we
    fall back to the first registered impl — the user-added-file case.

    Returns the matching :class:`FragmentImplSpec`, or ``None`` when
    the fragment has no implementations registered.
    """
    impls = fragment.implementations
    if not impls:
        return None
    # First pass: prefer an impl whose files_dir already carries the
    # rel_path. That's the typical "fragment file the user edited" case.
    from forge.fragments import _resolve_fragment_dir  # noqa: PLC0415

    for impl in impls.values():
        try:
            fragment_dir = _resolve_fragment_dir(impl.fragment_dir)
        except Exception:  # noqa: BLE001 — registry-level path resolution glitch.
            continue
        if (fragment_dir / "files" / cand.rel_path).is_file():
            return impl
    # Fallback: take the first impl. New fragment file case — the
    # operator added a file the fragment didn't previously ship. We
    # land it on whatever impl is first registered.
    return next(iter(impls.values()))


def _resolve_fragment_dir_under(
    *,
    forge_repo: Path,
    fragment_dir_str: str,
) -> Path | None:
    """Resolve a fragment's directory relative to a user-supplied forge_repo.

    Mirrors :func:`forge.feature_injector._resolve_fragment_dir`, but
    re-roots paths so tests (and CLI invocations against an alternate
    forge checkout) can target a tmp_path clone of the source tree
    without mutating the real installed package.

    Two layouts are honoured:

    * **Relative paths** (``"<fragment>"``) — built-in fragments under
      ``forge/templates/_fragments/<fragment>``. Resolved by joining
      against ``forge_repo / forge / templates / _fragments``.
    * **Absolute paths** under the live forge package — feature
      fragments registered with ``str(_TEMPLATES / name / lang)``.
      We remap by detecting the substring ``forge/features/`` (or
      ``forge\\features\\``) inside the absolute path and re-rooting
      the matching ``forge/features/...`` tail under ``forge_repo``.
      A pure plugin path (anything else) is honoured verbatim — the
      caller's forge_repo doesn't apply.

    Returns ``None`` when nothing resolves; the caller surfaces this
    as an ``errored`` apply entry rather than crashing.
    """
    path = Path(fragment_dir_str)
    if path.is_absolute():
        # Feature fragments (``forge/features/<area>/...``) live inside
        # the forge package and need re-rooting to the clone so apply-
        # back doesn't mutate the real installed package. Detect the
        # boundary by walking up the absolute path until we hit a
        # parent named ``forge`` whose child named ``features`` exists.
        # If we find one, rebase the tail under ``forge_repo``.
        parts = path.parts
        for i in range(len(parts) - 1, -1, -1):
            if parts[i] == "forge" and i + 1 < len(parts) and parts[i + 1] == "features":
                tail = parts[i:]
                rebased = forge_repo.joinpath(*tail)
                if rebased.is_dir():
                    return rebased
                # If the rebased path doesn't exist on the clone yet
                # (uncommon — the clone mirrors the full tree), fall
                # back to the absolute path so the apply still lands
                # somewhere predictable.
                return rebased
            if parts[i] == "forge" and i + 1 < len(parts) and parts[i + 1] == "templates":
                tail = parts[i:]
                rebased = forge_repo.joinpath(*tail)
                if rebased.is_dir():
                    return rebased
                return rebased
        # Plugin / absolute fragment dir outside the forge package —
        # honour verbatim. The caller's forge_repo doesn't apply.
        return path

    # Built-in fragments under templates/_fragments/. The relative
    # path stored on the impl spec is interpreted against the
    # templates/_fragments/ root.
    candidate = forge_repo / "forge" / "templates" / "_fragments" / fragment_dir_str
    if candidate.is_dir():
        return candidate

    # Fall through: try without the ``forge/`` prefix in case the
    # caller passed the inner ``forge`` package as forge_repo.
    candidate2 = forge_repo / "templates" / "_fragments" / fragment_dir_str
    if candidate2.is_dir():
        return candidate2

    return None


# ---------------------------------------------------------------------------
# Deps / env appliers — text-substitution rewrite of fragments.py
# ---------------------------------------------------------------------------
#
# Where files/block appliers rewrite the per-fragment template tree
# (``files/<rel>`` or ``inject.yaml``), deps/env appliers rewrite the
# Python source that REGISTERS the fragment. The fragment registry is
# materialised by importing ``forge/features/<area>/fragments.py``
# (and equivalent plugin modules), which call
# ``register_fragment(Fragment(name=..., implementations={lang:
# FragmentImplSpec(dependencies=(...), env_vars=((...),))}))``.
# Mutating ``dependencies`` / ``env_vars`` therefore means editing the
# Python literal inside that ``FragmentImplSpec(...)`` call.
#
# The approach is deliberately pragmatic — same trade-off as the block
# applier (text-based YAML rewrite, not AST round-trip):
#
# 1. Find the source file that registers the fragment. We walk every
#    ``forge/features/*/fragments.py`` (and any path the caller seeded
#    via ``forge_repo``) and ``grep`` for ``name="<fragment_name>"``
#    inside a ``register_fragment(...)`` block. The match is by literal
#    string, so a fragment registered with a constant-expression name
#    (rare; ``Fragment(name=NAME, ...)`` with ``NAME = "..."``) falls
#    through. Tests that exercise the matrix register inline and pass
#    a synthetic ``forge_repo`` so this lookup is self-contained.
#
# 2. Within that fragment's ``register_fragment(...)`` block, locate
#    the right ``FragmentImplSpec(...)`` call. For deps, language is
#    inferred from ``cand.rel_path`` (``pyproject.toml`` → PYTHON,
#    ``package.json`` → NODE, ``Cargo.toml`` → RUST). For env we
#    operate on every impl that declares the key (env_vars are shared
#    across the per-language impls semantically, even though they
#    duplicate at the spec level).
#
# 3. Inside the matching ``FragmentImplSpec(...)`` block, find the
#    ``dependencies=(...)`` (or ``env_vars=((...),)``) tuple. Parse
#    its contents via :mod:`ast.literal_eval`. If the expression is
#    NOT a literal tuple (e.g. ``base_deps + (...)``,
#    ``Fragment.python_deps()``), fall back to ``deferred`` with a
#    documented reason.
#
# 4. Mutate the parsed tuple per action and re-serialise via a small
#    formatter that preserves single-element tuple shape ``("foo",)``
#    and empty-tuple shape ``()`` to match how the registry sources
#    are conventionally formatted.
#
# 5. Replace the original tuple text with the formatted output, write
#    the file back. Surrounding whitespace + comments outside the
#    tuple span survive verbatim.
#
# Idempotency: a re-run on an already-applied bundle sees the
# expected post-state already on disk (e.g. the new dep present for
# ``added``, the old dep gone for ``removed``) and emits
# ``skipped-unchanged`` — matching the accept-harvested verb's
# vocabulary.


def _apply_deps_candidate(
    cand: CandidatePatch,
    *,
    forge_repo: Path,
    quiet: bool,
) -> ApplyBundleEntry:
    """Apply a ``kind="deps"`` candidate to fragments.py.

    Parses the candidate's structured-JSON ``diff`` payload, locates
    the fragment-registering source file, identifies the right
    ``FragmentImplSpec(...)`` by inferred backend language, and
    rewrites the ``dependencies=(...)`` tuple.

    Returns an :class:`ApplyBundleEntry` capturing the outcome.
    Errors are recorded, never raised.
    """
    fragment = FRAGMENT_REGISTRY.get(cand.fragment)
    if fragment is None:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"fragment {cand.fragment!r} not in registry",
        )

    try:
        payload = json.loads(cand.diff)
    except (ValueError, json.JSONDecodeError) as e:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"deps candidate diff is not valid JSON: {e}",
        )
    if not isinstance(payload, dict):
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error="deps candidate diff payload must be a JSON object",
        )

    action = payload.get("action")
    name = payload.get("name")
    fragment_spec = payload.get("fragment_spec")
    project_spec = payload.get("project_spec")

    if action not in ("added", "removed", "modified"):
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"deps candidate action {action!r} not in {{added, removed, modified}}",
        )
    if not isinstance(name, str) or not name:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error="deps candidate missing dep name",
        )

    lang = _lang_from_manifest_relpath(cand.rel_path)
    if lang is None:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=(
                f"cannot infer backend language from rel_path={cand.rel_path!r} "
                f"(expected pyproject.toml / package.json / Cargo.toml)"
            ),
        )

    source_path = _find_fragment_source_file(cand.fragment, forge_repo=forge_repo)
    if source_path is None:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=(
                f"could not locate fragments.py registering fragment {cand.fragment!r} "
                f"under forge_repo={forge_repo}"
            ),
        )

    try:
        result = _rewrite_fragment_deps(
            source_path=source_path,
            fragment_name=cand.fragment,
            lang=lang,
            action=action,
            dep_name=name,
            fragment_spec=fragment_spec,
            project_spec=project_spec,
        )
    except OSError as e:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            target=str(source_path),
            error=f"write failed: {e}",
        )

    if not quiet and result.status == "applied":
        print(f"  [apply-bundle] deps {cand.fragment}/{name} → {source_path}")

    return ApplyBundleEntry(
        fragment=cand.fragment,
        kind=cand.kind,
        rel_path=cand.rel_path,
        status=result.status,
        target=str(source_path),
        error=result.reason,
    )


def _apply_env_candidate(
    cand: CandidatePatch,
    *,
    forge_repo: Path,
    quiet: bool,
) -> ApplyBundleEntry:
    """Apply a ``kind="env"`` candidate to fragments.py.

    Mirrors :func:`_apply_deps_candidate` but operates on the
    ``env_vars=((...),)`` tuple-of-tuples. Unlike deps the language
    is not inferred from ``rel_path`` (env vars are always in
    ``.env.example`` regardless of backend); instead the applier
    rewrites every impl that declares the key. If no impl declares
    the key (the ``added`` action), the applier picks the first
    language the fragment registers — env vars are conventionally
    shared across all languages, so this matches the convention.
    """
    fragment = FRAGMENT_REGISTRY.get(cand.fragment)
    if fragment is None:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"fragment {cand.fragment!r} not in registry",
        )

    try:
        payload = json.loads(cand.diff)
    except (ValueError, json.JSONDecodeError) as e:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"env candidate diff is not valid JSON: {e}",
        )
    if not isinstance(payload, dict):
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error="env candidate diff payload must be a JSON object",
        )

    action = payload.get("action")
    key = payload.get("key")
    fragment_value = payload.get("fragment_value")
    project_value = payload.get("project_value")

    if action not in ("added", "removed", "modified"):
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"env candidate action {action!r} not in {{added, removed, modified}}",
        )
    if not isinstance(key, str) or not key:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error="env candidate missing env key",
        )

    source_path = _find_fragment_source_file(cand.fragment, forge_repo=forge_repo)
    if source_path is None:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=(
                f"could not locate fragments.py registering fragment {cand.fragment!r} "
                f"under forge_repo={forge_repo}"
            ),
        )

    try:
        result = _rewrite_fragment_env_vars(
            source_path=source_path,
            fragment_name=cand.fragment,
            action=action,
            key=key,
            fragment_value=fragment_value,
            project_value=project_value,
        )
    except OSError as e:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            target=str(source_path),
            error=f"write failed: {e}",
        )

    if not quiet and result.status == "applied":
        print(f"  [apply-bundle] env {cand.fragment}/{key} → {source_path}")

    return ApplyBundleEntry(
        fragment=cand.fragment,
        kind=cand.kind,
        rel_path=cand.rel_path,
        status=result.status,
        target=str(source_path),
        error=result.reason,
    )


def _lang_from_manifest_relpath(rel_path: str) -> BackendLanguage | None:
    """Infer the backend language from a deps candidate's ``rel_path``.

    Mirrors the inverse of :func:`forge.extractors.deps._manifest_path`.
    The extractor stamps ``rel_path = manifest_path.name``, so the bare
    filename is what we get back. Returns ``None`` if it doesn't match
    one of the three built-in manifest files — callers surface that as
    ``errored``.
    """
    name = Path(rel_path).name
    if name == "pyproject.toml":
        return BackendLanguage.PYTHON
    if name == "package.json":
        return BackendLanguage.NODE
    if name == "Cargo.toml":
        return BackendLanguage.RUST
    return None


def _find_fragment_source_file(fragment_name: str, *, forge_repo: Path) -> Path | None:
    """Locate the ``fragments.py`` module that registers ``fragment_name``.

    Walks the conventional locations:

    * ``<forge_repo>/forge/features/*/fragments.py`` — built-in
      feature fragments. This is where ~95% of registrations live.
    * Plugin paths: any ``*.py`` directly under ``<forge_repo>`` whose
      contents include the registration pattern. Tests pass a
      synthetic forge_repo containing inline ``fragments.py`` files
      so this catch-all picks them up without a registry plumbing
      pass.

    The match is a literal-string grep for ``name="<fragment_name>"``
    or ``name='<fragment_name>'`` appearing inside a
    ``register_fragment(`` call. A fragment registered via a constant-
    expression name (``Fragment(name=NAME, ...)``) is NOT matched —
    that's the documented limitation, the applier falls back to
    ``deferred`` in callers when this returns ``None``.

    Returns the absolute path to the registering file, or ``None``
    when no match found.
    """
    # Build the candidate haystack. Conventional registrations come
    # from forge/features/*/fragments.py (built-ins). Tests + plugins
    # may also register from any .py under forge_repo; the catch-all
    # glob keeps the discovery uniform.
    candidates: list[Path] = []
    feature_dir = forge_repo / "forge" / "features"
    if feature_dir.is_dir():
        candidates.extend(feature_dir.glob("*/fragments.py"))
    # Plugin / inline registrations. We don't recurse into every
    # subdirectory by default (that would scan the whole project
    # tree); we honour the top-level *.py files of forge_repo, which
    # covers the test scaffold pattern (a tmp_path with an inline
    # fragments.py at the root).
    candidates.extend(forge_repo.glob("*.py"))
    # Also accept fragments.py inside one-level-deep subdirs of
    # forge_repo (catches plugin packages laid out as
    # ``<plugin>/fragments.py`` in tests).
    candidates.extend(forge_repo.glob("*/fragments.py"))

    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _source_registers_fragment(text, fragment_name):
            return path
    return None


def _source_registers_fragment(source: str, fragment_name: str) -> bool:
    """Return True if ``source`` contains a ``register_fragment`` call
    registering ``fragment_name`` (literal-string match)."""
    # Match name="<x>" or name='<x>' anywhere in the source — we
    # narrow further by re-checking the register_fragment boundary
    # inside the rewriters.
    pattern_dq = f'name="{fragment_name}"'
    pattern_sq = f"name='{fragment_name}'"
    return pattern_dq in source or pattern_sq in source


@dataclass(frozen=True)
class _RewriteResult:
    """Outcome of an in-place fragments.py rewrite.

    Attributes:
        status: ``"applied"`` / ``"skipped-unchanged"`` / ``"deferred"``
            / ``"errored"``. Caller maps to the ``ApplyBundleEntry``.
        reason: Free-form note for the operator. Empty when applied.
    """

    status: str
    reason: str = ""


def _rewrite_fragment_deps(
    *,
    source_path: Path,
    fragment_name: str,
    lang: BackendLanguage,
    action: str,
    dep_name: str,
    fragment_spec: str | None,
    project_spec: str | None,
) -> _RewriteResult:
    """Rewrite the ``dependencies=(...)`` tuple for ``fragment_name``/``lang``.

    Returns a :class:`_RewriteResult` describing the outcome. The
    caller wraps the result in an :class:`ApplyBundleEntry`.

    Contract:
      * ``action="added"`` — append ``project_spec`` (the project's
        on-disk version) to the existing tuple, IF not already
        present. If already present → ``skipped-unchanged``.
      * ``action="removed"`` — drop ``fragment_spec`` from the tuple,
        IF present. If absent → ``skipped-unchanged``.
      * ``action="modified"`` — replace ``fragment_spec`` with
        ``project_spec``. If ``fragment_spec`` is absent but
        ``project_spec`` is already there → ``skipped-unchanged``.

    The text substitution operates on a literal ``(...)`` tuple
    expression following the ``dependencies=`` keyword inside the
    matching :class:`FragmentImplSpec` block. Non-literal expressions
    fall back to ``deferred``.
    """
    source = source_path.read_text(encoding="utf-8")
    span = _locate_impl_kwarg_span(
        source,
        fragment_name=fragment_name,
        lang=lang,
        kwarg="dependencies",
    )
    if span.status != "ok":
        return _RewriteResult(status=span.status, reason=span.reason)

    assert span.start is not None and span.end is not None
    raw_tuple = source[span.start : span.end]

    try:
        current = ast.literal_eval(raw_tuple)
    except (SyntaxError, ValueError):
        return _RewriteResult(
            status="deferred",
            reason=(
                f"dependencies expression for fragment {fragment_name!r} "
                f"({lang.value}) is not a literal tuple; manual edit required"
            ),
        )
    if not isinstance(current, tuple):
        return _RewriteResult(
            status="deferred",
            reason=(
                f"dependencies expression for fragment {fragment_name!r} "
                f"({lang.value}) is not a tuple; manual edit required"
            ),
        )

    # Normalise to a list[str] so the mutation is straightforward.
    deps_list: list[str] = [str(d) for d in current]

    if action == "added":
        if project_spec is None:
            return _RewriteResult(
                status="errored",
                reason="deps 'added' candidate missing project_spec",
            )
        if project_spec in deps_list:
            return _RewriteResult(
                status="skipped-unchanged",
                reason=f"dep {project_spec!r} already present",
            )
        deps_list.append(project_spec)
    elif action == "removed":
        if fragment_spec is None:
            return _RewriteResult(
                status="errored",
                reason="deps 'removed' candidate missing fragment_spec",
            )
        if fragment_spec not in deps_list:
            return _RewriteResult(
                status="skipped-unchanged",
                reason=f"dep {fragment_spec!r} already absent",
            )
        deps_list.remove(fragment_spec)
    else:  # action == "modified"
        if fragment_spec is None or project_spec is None:
            return _RewriteResult(
                status="errored",
                reason="deps 'modified' candidate missing fragment_spec or project_spec",
            )
        if fragment_spec not in deps_list:
            # Maybe already updated — check.
            if project_spec in deps_list:
                return _RewriteResult(
                    status="skipped-unchanged",
                    reason=f"dep already at {project_spec!r}",
                )
            return _RewriteResult(
                status="errored",
                reason=(
                    f"dep {fragment_spec!r} not found in current tuple; current: {deps_list!r}"
                ),
            )
        idx = deps_list.index(fragment_spec)
        deps_list[idx] = project_spec

    new_tuple_text = _format_str_tuple(
        deps_list,
        leading_indent=_detect_indent_for_kwarg(source, span.start),
    )
    new_source = source[: span.start] + new_tuple_text + source[span.end :]
    source_path.write_text(new_source, encoding="utf-8")
    return _RewriteResult(status="applied")


def _rewrite_fragment_env_vars(
    *,
    source_path: Path,
    fragment_name: str,
    action: str,
    key: str,
    fragment_value: str | None,
    project_value: str | None,
) -> _RewriteResult:
    """Rewrite the ``env_vars=((...),)`` tuple-of-tuples for ``fragment_name``.

    Env vars are typically the same across the per-language impls of
    a fragment, so this rewrites EVERY language impl that ships an
    ``env_vars=(...)`` tuple. The result is ``applied`` when at least
    one impl was rewritten; ``skipped-unchanged`` when every impl
    already carries the post-state; ``deferred`` when at least one
    impl's expression is non-literal; ``errored`` for action-specific
    payload issues.

    The tuple-of-tuples shape is ``((KEY, VALUE), (KEY, VALUE), ...)``.
    Single-element shape is ``((KEY, VALUE),)`` (trailing comma for the
    outer tuple). Empty shape is ``()``.
    """
    source = source_path.read_text(encoding="utf-8")

    # Find EVERY env_vars span inside the matching register_fragment
    # block. Each one corresponds to one FragmentImplSpec(...) inside
    # the implementations={} dict. We rewrite all of them so the
    # fragment's per-language impls stay in sync.
    spans, non_literal = _locate_all_env_vars_spans(source, fragment_name=fragment_name)
    if non_literal is not None:
        # At least one impl carries a non-literal env_vars expression.
        # We defer the whole apply — partial mutation would leave the
        # fragment's per-language impls inconsistent, and the
        # documented contract is "fall back to manual edit when the
        # tuple isn't a Python literal".
        return _RewriteResult(
            status=non_literal.status,
            reason=non_literal.reason,
        )
    if not spans:
        return _RewriteResult(
            status="errored",
            reason=(
                f"no FragmentImplSpec with an env_vars=(...) tuple found for "
                f"fragment {fragment_name!r}; fragment may not declare env vars"
            ),
        )

    # First pass — parse every span; bail to deferred on the first
    # non-literal so we don't mutate any file we'd later refuse to
    # finish.
    parsed: list[tuple[int, int, list[tuple[str, str]]]] = []
    for start, end in spans:
        raw = source[start:end]
        try:
            current = ast.literal_eval(raw)
        except (SyntaxError, ValueError):
            return _RewriteResult(
                status="deferred",
                reason=(
                    f"env_vars expression for fragment {fragment_name!r} "
                    f"is not a literal tuple; manual edit required"
                ),
            )
        if not isinstance(current, tuple):
            return _RewriteResult(
                status="deferred",
                reason=(
                    f"env_vars expression for fragment {fragment_name!r} "
                    f"is not a tuple; manual edit required"
                ),
            )
        pairs: list[tuple[str, str]] = []
        for item in current:
            if not (isinstance(item, tuple) and len(item) == 2):
                return _RewriteResult(
                    status="deferred",
                    reason=(
                        f"env_vars contains a non-2-tuple item for fragment "
                        f"{fragment_name!r}; manual edit required"
                    ),
                )
            pairs.append((str(item[0]), str(item[1])))
        parsed.append((start, end, pairs))

    # Mutate every span. ``unchanged_count`` lets us emit
    # ``skipped-unchanged`` when every impl already carries the
    # post-state.
    mutated_spans: list[tuple[int, int, list[tuple[str, str]]]] = []
    unchanged_count = 0
    for start, end, pairs in parsed:
        existing_keys = {k for k, _ in pairs}
        if action == "added":
            if project_value is None:
                return _RewriteResult(
                    status="errored",
                    reason="env 'added' candidate missing project_value",
                )
            if key in existing_keys and (key, project_value) in pairs:
                unchanged_count += 1
                mutated_spans.append((start, end, pairs))
                continue
            if key in existing_keys:
                # The key already exists but with a different value
                # — treat as modified semantically. Replace.
                pairs = [(k, project_value if k == key else v) for k, v in pairs]
            else:
                pairs = [*pairs, (key, project_value)]
        elif action == "removed":
            if fragment_value is None:
                return _RewriteResult(
                    status="errored",
                    reason="env 'removed' candidate missing fragment_value",
                )
            if (key, fragment_value) not in pairs and key not in existing_keys:
                unchanged_count += 1
                mutated_spans.append((start, end, pairs))
                continue
            pairs = [(k, v) for k, v in pairs if k != key]
        else:  # action == "modified"
            if fragment_value is None or project_value is None:
                return _RewriteResult(
                    status="errored",
                    reason="env 'modified' candidate missing fragment_value or project_value",
                )
            if (key, project_value) in pairs and (key, fragment_value) not in pairs:
                unchanged_count += 1
                mutated_spans.append((start, end, pairs))
                continue
            if key not in existing_keys:
                return _RewriteResult(
                    status="errored",
                    reason=(
                        f"env key {key!r} not found in current tuple for fragment "
                        f"{fragment_name!r}; current: {pairs!r}"
                    ),
                )
            pairs = [(k, project_value if k == key else v) for k, v in pairs]
        mutated_spans.append((start, end, pairs))

    if unchanged_count == len(parsed):
        return _RewriteResult(
            status="skipped-unchanged",
            reason=f"env_vars for {key!r} already at expected state",
        )

    # Apply mutations in reverse order so byte offsets stay valid as
    # we splice each replacement in.
    new_source = source
    for start, end, pairs in reversed(mutated_spans):
        new_text = _format_env_vars_tuple(
            pairs,
            leading_indent=_detect_indent_for_kwarg(source, start),
        )
        new_source = new_source[:start] + new_text + new_source[end:]
    source_path.write_text(new_source, encoding="utf-8")
    return _RewriteResult(status="applied")


@dataclass(frozen=True)
class _KwargSpan:
    """Result of looking up a kwarg's tuple-expression span.

    ``status`` is ``"ok"`` when the span is valid; otherwise it's the
    ``ApplyBundleEntry`` status the caller should emit and ``reason``
    explains it.
    """

    status: str
    reason: str = ""
    start: int | None = None
    end: int | None = None


def _locate_impl_kwarg_span(
    source: str,
    *,
    fragment_name: str,
    lang: BackendLanguage,
    kwarg: str,
) -> _KwargSpan:
    """Locate the byte span of a ``<kwarg>=(...)`` tuple inside a
    fragment's per-language ``FragmentImplSpec(...)`` block.

    Strategy:

    1. Find the ``register_fragment(`` opening boundary that contains
       ``name="<fragment_name>"`` (or single-quoted). Anchor on the
       fragment's name to scope the search.
    2. Within that ``register_fragment`` call, locate the
       ``BackendLanguage.<LANG>: FragmentImplSpec(`` opening. The
       language enum's name (``PYTHON`` / ``NODE`` / ``RUST``) is
       what conventional fragments.py modules write.
    3. Inside that ``FragmentImplSpec(`` call, find the
       ``<kwarg>=`` keyword, then read the matching ``(`` ...
       ``)`` span via balanced-parenthesis counting (respects nested
       parens, ignores parens inside string literals).

    Returns a :class:`_KwargSpan` with ``status="ok"`` and the
    half-open byte span ``[start, end)`` covering the literal tuple
    text (including outer parentheses). On any failure to anchor,
    returns a non-ok status the caller surfaces verbatim.
    """
    reg_start, reg_end = _find_register_fragment_block(source, fragment_name)
    if reg_start < 0:
        return _KwargSpan(
            status="errored",
            reason=(
                f"register_fragment(Fragment(name={fragment_name!r}, ...)) not found in source"
            ),
        )

    # Inside the register_fragment block, find the per-language impl
    # entry. The conventional shape is
    # ``BackendLanguage.PYTHON: FragmentImplSpec(...)``.
    lang_token = f"BackendLanguage.{lang.name}"
    impl_idx = source.find(lang_token, reg_start, reg_end)
    if impl_idx < 0:
        return _KwargSpan(
            status="errored",
            reason=(
                f"fragment {fragment_name!r} has no {lang.name} implementation in source "
                f"(no '{lang_token}:' inside the register_fragment block)"
            ),
        )
    # Find the FragmentImplSpec( opening after this language token.
    impl_open = source.find("FragmentImplSpec(", impl_idx, reg_end)
    if impl_open < 0:
        return _KwargSpan(
            status="errored",
            reason=(
                f"fragment {fragment_name!r}/{lang.name}: language token "
                f"present but no FragmentImplSpec( follows"
            ),
        )
    impl_paren_open = source.find("(", impl_open, reg_end)
    impl_paren_close = _matching_paren(source, impl_paren_open)
    if impl_paren_close < 0:
        return _KwargSpan(
            status="errored",
            reason=(
                f"unbalanced parentheses in FragmentImplSpec(...) for {fragment_name!r}/{lang.name}"
            ),
        )

    return _scan_kwarg_tuple_span(
        source,
        scope_start=impl_paren_open + 1,
        scope_end=impl_paren_close,
        kwarg=kwarg,
    )


def _locate_all_env_vars_spans(
    source: str,
    *,
    fragment_name: str,
) -> tuple[list[tuple[int, int]], _KwargSpan | None]:
    """Return every ``env_vars=(...)`` tuple span inside the fragment's
    register_fragment block, one per ``FragmentImplSpec(...)``.

    The order mirrors the source-code order so the rewriter can
    splice in reverse and keep byte offsets stable.

    Returns ``(spans, non_ok_span)``:

    * ``spans`` — list of ``(start, end)`` byte spans for every
      ``FragmentImplSpec`` that has a LITERAL ``env_vars=(...)``
      tuple. Empty when none of the impls declare env_vars.
    * ``non_ok_span`` — the first :class:`_KwargSpan` (status !=
      ``"ok"``) encountered. ``None`` if every impl that declared
      env_vars was a literal tuple. Caller surfaces this to the
      operator so a fragment with a non-literal env_vars expression
      lands as ``deferred`` rather than silently skipping the impl.
    """
    reg_start, reg_end = _find_register_fragment_block(source, fragment_name)
    if reg_start < 0:
        return [], None
    spans: list[tuple[int, int]] = []
    first_non_ok: _KwargSpan | None = None
    # Walk every FragmentImplSpec( opening inside the block.
    cursor = reg_start
    while True:
        open_idx = source.find("FragmentImplSpec(", cursor, reg_end)
        if open_idx < 0:
            break
        paren_open = source.find("(", open_idx, reg_end)
        paren_close = _matching_paren(source, paren_open)
        if paren_close < 0:
            break
        span = _scan_kwarg_tuple_span(
            source,
            scope_start=paren_open + 1,
            scope_end=paren_close,
            kwarg="env_vars",
        )
        if span.status == "ok" and span.start is not None and span.end is not None:
            spans.append((span.start, span.end))
        elif span.status == "deferred" and first_non_ok is None:
            # The kwarg exists but isn't a literal tuple — record so
            # the caller can surface it. We DON'T treat the
            # ``errored`` shape ("FragmentImplSpec has no env_vars
            # keyword") as a non-ok span: a fragment can omit
            # env_vars entirely on a per-language impl, which is
            # legitimate and shouldn't poison the others.
            first_non_ok = span
        cursor = paren_close + 1
    return spans, first_non_ok


def _scan_kwarg_tuple_span(
    source: str,
    *,
    scope_start: int,
    scope_end: int,
    kwarg: str,
) -> _KwargSpan:
    """Find the ``<kwarg>=`` keyword inside ``[scope_start, scope_end)``
    and return the matching parenthesised tuple span."""
    pattern = re.compile(rf"\b{re.escape(kwarg)}\s*=\s*")
    for match in pattern.finditer(source, scope_start, scope_end):
        # We need to be sure this match is at the kwarg-list level
        # of the FragmentImplSpec call, not nested inside another
        # tuple. Check the immediately-preceding non-whitespace char
        # is either ``,`` (a prior kwarg) or ``(`` (the call opener).
        prev_idx = match.start() - 1
        while prev_idx >= scope_start and source[prev_idx] in " \t\n":
            prev_idx -= 1
        if prev_idx < scope_start:
            continue
        if source[prev_idx] not in ",(":
            continue
        eq_end = match.end()
        if eq_end >= scope_end:
            continue
        # Find the opening ``(``. The kwarg value must start with a
        # ``(`` for us to treat it as a literal tuple. Anything else
        # (an identifier, a function call, a list comprehension) we
        # defer.
        # Skip whitespace after ``=``.
        idx = eq_end
        while idx < scope_end and source[idx] in " \t\n":
            idx += 1
        if idx >= scope_end or source[idx] != "(":
            return _KwargSpan(
                status="deferred",
                reason=(f"{kwarg} value is not a literal tuple expression; manual edit required"),
            )
        close = _matching_paren(source, idx)
        if close < 0 or close >= scope_end:
            return _KwargSpan(
                status="errored",
                reason=f"{kwarg} tuple has unbalanced parentheses",
            )
        return _KwargSpan(status="ok", start=idx, end=close + 1)
    return _KwargSpan(
        status="errored",
        reason=f"FragmentImplSpec(...) has no {kwarg}=(...) keyword",
    )


def _find_register_fragment_block(source: str, fragment_name: str) -> tuple[int, int]:
    """Return the ``(open_paren, close_paren)`` span of the
    ``register_fragment(...)`` call that registers ``fragment_name``.

    Walks every ``register_fragment(`` occurrence; for each, finds its
    matching close paren and checks whether the enclosed text mentions
    ``name="<fragment_name>"`` (or single-quoted). Returns the first
    matching span. Returns ``(-1, -1)`` when none match.

    The matching close-paren includes the OUTER ``)`` of
    ``register_fragment(Fragment(name=..., ...))``, so callers can
    use ``[open+1, close)`` as the scope for kwarg lookups inside.
    """
    pattern_dq = f'name="{fragment_name}"'
    pattern_sq = f"name='{fragment_name}'"
    pos = 0
    while True:
        idx = source.find("register_fragment(", pos)
        if idx < 0:
            return -1, -1
        open_paren = source.find("(", idx)
        close_paren = _matching_paren(source, open_paren)
        if close_paren < 0:
            return -1, -1
        block_text = source[open_paren : close_paren + 1]
        if pattern_dq in block_text or pattern_sq in block_text:
            return open_paren, close_paren
        pos = close_paren + 1


def _matching_paren(source: str, open_idx: int) -> int:
    """Return the index of the ``)`` matching the ``(`` at ``open_idx``.

    Respects nested parentheses, brackets, and braces, and skips
    parentheses appearing inside string literals (single, double,
    and triple-quoted). Returns ``-1`` on unbalanced input.
    """
    if open_idx < 0 or open_idx >= len(source) or source[open_idx] != "(":
        return -1
    depth = 0
    i = open_idx
    n = len(source)
    while i < n:
        ch = source[i]
        if ch in ("'", '"'):
            quote, end = _skip_string_literal(source, i)
            if end < 0:
                return -1
            i = end
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return i
        elif ch == "#":
            # Comment to end of line.
            nl = source.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        i += 1
    return -1


def _skip_string_literal(source: str, start: int) -> tuple[str, int]:
    """Advance past a Python string literal starting at ``source[start]``.

    Handles single/double-quoted single-line strings, triple-quoted
    multi-line strings, and ``r``/``b``/``f`` prefix combinations
    via the caller already pointing at the opening quote. Returns
    ``(quote_char, index_after_closing_quote)``. Returns
    ``(quote, -1)`` if the literal is unterminated.
    """
    quote = source[start]
    if start + 2 < len(source) and source[start : start + 3] == quote * 3:
        # Triple-quoted.
        close = source.find(quote * 3, start + 3)
        if close < 0:
            return quote, -1
        return quote, close + 3
    # Single-quoted. Handle backslash escapes.
    i = start + 1
    n = len(source)
    while i < n:
        ch = source[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == quote:
            return quote, i + 1
        if ch == "\n":
            # Single-line literal closed unexpectedly — treat as
            # unterminated.
            return quote, -1
        i += 1
    return quote, -1


def _detect_indent_for_kwarg(source: str, kwarg_open_idx: int) -> str:
    """Return the indentation prefix of the line containing
    ``source[kwarg_open_idx]``.

    Used by the tuple formatter to align continuation lines with the
    original kwarg's column. A multi-line tuple keeps the indent
    convention even after rewrite.
    """
    line_start = source.rfind("\n", 0, kwarg_open_idx) + 1
    indent_chars: list[str] = []
    i = line_start
    while i < kwarg_open_idx and source[i] in " \t":
        indent_chars.append(source[i])
        i += 1
    return "".join(indent_chars)


def _format_str_tuple(items: list[str], *, leading_indent: str) -> str:
    """Format a list of strings as a Python tuple literal.

    Single-line for empty / single-element tuples; multi-line with
    trailing commas for two-or-more elements. The ``leading_indent``
    is used for continuation lines so the formatted tuple aligns with
    the surrounding code.
    """
    if not items:
        return "()"
    if len(items) == 1:
        return f"({_repr_str(items[0])},)"
    # Multi-line. The opening ``(`` stays inline with the kwarg; each
    # element gets its own line with +4 spaces; the closing ``)`` aligns
    # with the kwarg's indent.
    body_indent = leading_indent + "    "
    lines = ["("]
    for item in items:
        lines.append(f"{body_indent}{_repr_str(item)},")
    lines.append(f"{leading_indent})")
    return "\n".join(lines)


def _format_env_vars_tuple(
    pairs: list[tuple[str, str]],
    *,
    leading_indent: str,
) -> str:
    """Format ``((KEY, VALUE), ...)`` for the env_vars kwarg.

    Single-element tuple keeps the trailing comma on the OUTER tuple
    (``((KEY, VAL),)``) to match the source convention. Empty tuple
    is ``()``. Multi-element wraps onto multiple lines.
    """
    if not pairs:
        return "()"
    if len(pairs) == 1:
        k, v = pairs[0]
        return f"(({_repr_str(k)}, {_repr_str(v)}),)"
    body_indent = leading_indent + "    "
    lines = ["("]
    for k, v in pairs:
        lines.append(f"{body_indent}({_repr_str(k)}, {_repr_str(v)}),")
    lines.append(f"{leading_indent})")
    return "\n".join(lines)


def _repr_str(s: str) -> str:
    """Render ``s`` as a Python string literal.

    Uses double quotes when the string contains no double quotes, else
    falls back to single quotes — mirrors the convention forge's own
    fragments.py modules use (most strings double-quoted; specs that
    embed quotes single-quoted).
    """
    if '"' not in s:
        return f'"{s}"'
    if "'" not in s:
        return f"'{s}'"
    # Both quote chars appear — fall back to double-quoting with
    # escapes. Rare in practice.
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
