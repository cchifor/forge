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
    with the candidate's current content. Two sub-paths split on
    :attr:`CandidatePatch.risk`:
      - ``risk="safe-apply"`` (the LITERAL path) — wholesale replace.
        The file extractor only emits ``safe-apply`` when the fragment
        baseline equals the upstream-emitted body, so the user's
        current text is the unambiguous new fragment content.
      - ``risk="conflict"`` (the STRUCTURAL path) — both the upstream
        fragment AND the user moved divergently. The applier writes
        the user's current text into the fragment tree (preserving
        the user's edits) AND emits a ``<target>.forge-merge`` sidecar
        carrying the upstream-emitted body so the maintainer can
        manually reconcile the two diverging trajectories. The
        ``ApplyBundleEntry`` reports ``status="applied"`` with the
        sidecar path on :attr:`ApplyBundleEntry.error` so the operator
        is alerted. See :func:`_apply_files_structural_candidate`.
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

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from forge.extractors.pipeline import CandidateKind, CandidatePatch

if TYPE_CHECKING:
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
    # Build the kind -> handler registry. Local imports avoid the
    # module-level cycle: per-kind handler modules import
    # :class:`ApplyBundleEntry` from this module, and this dispatcher
    # calls back into them.
    handlers = _build_apply_handlers()

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

        handler = handlers.get(cand.kind)
        if handler is None:
            # Unknown kind — record + continue rather than crash. The
            # operator's harvest tooling and the apply lane must agree
            # on the kind vocabulary; a mismatch is a bug worth
            # surfacing. The most common reason today is ``new-file``,
            # which is owned by the accept-baseline path, not by
            # apply_bundle; agents that forward a new-file candidate
            # here get a clean structured error.
            entry = ApplyBundleEntry(
                fragment=cand.fragment,
                kind=cand.kind,
                rel_path=cand.rel_path,
                status="errored",
                error=f"unknown candidate kind {cand.kind!r}",
            )
        else:
            entry = handler(cand, forge_repo=forge_repo, quiet=quiet)

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


# Initiative #1 sub-task 3 — kind dispatch via a typed registry instead
# of an if/elif ladder. Adding a new ``CandidateKind`` value now requires
# a registry entry (or an explicit "owned elsewhere" comment, the way
# ``new-file`` is); a missing entry surfaces as the existing structured
# "unknown candidate kind" error in the report, not as a silent fall-
# through. Plugin extractors that introduce their own kinds will plug in
# here in sub-task 4.


class ApplyHandler(Protocol):
    """Callable contract every kind-handler in :func:`_build_apply_handlers`
    must satisfy. Spells out the keyword-only ``forge_repo`` / ``quiet``
    parameters that ``Callable[..., ApplyBundleEntry]`` flattened away,
    so ty catches a handler with the wrong signature at registration
    time instead of at first call.
    """

    def __call__(
        self,
        cand: CandidatePatch,
        *,
        forge_repo: Path,
        quiet: bool,
    ) -> ApplyBundleEntry: ...


def _apply_cross_lang_suggest_candidate(
    cand: CandidatePatch,
    *,
    forge_repo: Path,  # noqa: ARG001 — uniform handler signature
    quiet: bool,  # noqa: ARG001 — uniform handler signature
) -> ApplyBundleEntry:
    """RFC-006 cross-language parity hint — never applied automatically.

    The candidate carries the path of a sibling-language impl the
    maintainer should mirror by hand. ``forge --emit-pr`` surfaces these
    in the reviewer checklist; apply-back records the deferral so the
    operator's report stays honest.
    """
    return ApplyBundleEntry(
        fragment=cand.fragment,
        kind=cand.kind,
        rel_path=cand.rel_path,
        target=cand.target_path or None,
        status="deferred",
        error="cross-lang suggestion; apply manually to the named impl",
    )


def _build_apply_handlers() -> dict[CandidateKind, ApplyHandler]:
    """Construct the kind -> handler map.

    Built per-call (not at module import) so the per-kind handler
    modules can keep importing :class:`ApplyBundleEntry` from this
    module without an import cycle.

    ``new-file`` is intentionally absent — that kind is owned by the
    accept-baseline path; routing it through apply_bundle is a
    contract bug and surfaces as a structured ``errored`` entry above.
    """
    from forge.sync.project_to_forge.apply_bundle._blocks import (  # noqa: PLC0415
        _apply_block_candidate,
    )
    from forge.sync.project_to_forge.apply_bundle._deps import (  # noqa: PLC0415
        _apply_deps_candidate,
    )
    from forge.sync.project_to_forge.apply_bundle._env import (  # noqa: PLC0415
        _apply_env_candidate,
    )
    from forge.sync.project_to_forge.apply_bundle._files_literal import (  # noqa: PLC0415
        _apply_files_candidate,
    )

    return {
        "files": _apply_files_candidate,
        "block": _apply_block_candidate,
        "deps": _apply_deps_candidate,
        "env": _apply_env_candidate,
        "cross-lang-suggest": _apply_cross_lang_suggest_candidate,
    }
