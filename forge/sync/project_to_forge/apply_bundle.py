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
  * ``kind="deps"`` / ``kind="env"`` → DEFERRED. These need structural
    reasoning (which fragment.dependencies field gets the addition?
    where do option-conditional deps go?) that is best handled
    interactively rather than by an automated lane.

The contract is intentionally narrow: ``apply_bundle_to_fragments`` is
the substrate that ``forge --harvest --accept`` (a Phase 6 CLI verb)
will sit on top of, plus the dependency the round-trip CI lane uses to
exercise the full forward→reverse→apply→forward cycle in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

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
            ``"env"``).
        rel_path: POSIX rel-path identifying the patch target inside the
            fragment tree (or the project tree, for ``"block"`` /
            ``"deps"`` / ``"env"``).
        status: One of ``"applied"`` (write succeeded), ``"skipped"``
            (filtered out by ``risk_filter``), ``"deferred"`` (kind not
            supported in v1 — see module docstring), or ``"errored"``
            (apply attempted but failed; see :attr:`error`).
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
      * ``kind="deps"`` / ``kind="env"`` → DEFERRED in v1. Same
        rationale; emit a ``deferred`` entry.

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
        else:
            # deps / env — still deferred. These need structural
            # reasoning (which fragment.dependencies field gets the
            # addition? what's option-conditional?) that's better
            # surfaced interactively than written by an automated lane.
            entry = ApplyBundleEntry(
                fragment=cand.fragment,
                kind=cand.kind,
                rel_path=cand.rel_path,
                status="deferred",
                error=(
                    f"kind={cand.kind!r} apply-back needs structural "
                    f"reasoning; surfaced for interactive review only"
                ),
            )

        entries.append(entry)
        if entry.status == "applied":
            applied += 1
        elif entry.status == "deferred":
            deferred += 1
        elif entry.status == "errored":
            errored += 1
        elif entry.status == "skipped":
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
    from forge.feature_injector import _resolve_fragment_dir  # noqa: PLC0415

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
