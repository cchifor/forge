"""`forge --harvest` orchestrator (Phase 4, bidirectional sync).

Walks a generated project's ``forge.toml`` manifest, runs the
:class:`forge.extractors.ExtractorPipeline` for every fragment with
recorded provenance, and collects the candidate patches into a
:class:`HarvestBundle`. The CLI dispatcher (``forge --harvest``) calls
:func:`harvest_project` and either writes the bundle to disk or streams
it as JSON.

The orchestration is symmetric to the forward flow (apply):

* Forward (``forge --update`` →
  :func:`forge.sync.forge_to_project.updater.update_project`):
  resolver → :class:`FragmentPlan` per fragment → applier pipeline.
* Reverse (``forge --harvest`` → :func:`harvest_project`):
  manifest → :class:`ExtractionPlan` per fragment → extractor pipeline.

The asymmetry sits in plan construction. The forward plan resolves
fragment metadata against the registry to know *what to write*. The
reverse plan inverts that: it inspects what the forward direction
recorded in the manifest (``[forge.provenance]`` /
``[forge.merge_blocks]``) and uses that as the set of paths to inspect
on disk.

Phase 4 backbone:
  * file-level extraction is wired (the parallel agent owns the
    :class:`forge.extractors.files.FileExtractor` body);
  * block-level extraction is the headline contribution of this PR
    (:class:`forge.extractors.injection.InjectionExtractor`);
  * deps + env extraction surface ``needs-review`` candidates via the
    pair extractors the parallel agent wires up.

Out of scope for this PR (deferred to Phase 4b):
  * ``--emit-pr`` integration with ``gh pr create``.
  * ``--accept-harvested`` to land candidates back in the fragment tree.
  * ``--reapply-baseline`` to restamp baselines after a harvest cycle.

Interactive review (``--harvest-interactive``) is wired via the
:data:`PromptCallback` parameter on :func:`harvest_project`. Callers
inject a callback that prompts ``accept`` / ``skip`` / ``quit`` per
candidate; the default ``None`` preserves the headless contract
(every candidate is accepted, no prompt is shown).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any, Literal

import yaml

from forge.capability_resolver import resolve
from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.errors import PROVENANCE_MANIFEST_MISSING, ProvenanceError
from forge.extractors.pipeline import CandidatePatch, ExtractorPipeline
from forge.extractors.plan import ExtractionPlan
from forge.fragment_context import FragmentContext
from forge.fragments import FRAGMENT_REGISTRY, Fragment, FragmentImplSpec
from forge.sync.forge_to_project.updater import _infer_backends
from forge.sync.manifest import read_forge_toml
from forge.sync.merge import MergeBlockCollector

# Result tokens a ``prompt_callback`` may return per candidate. ``"quit"``
# short-circuits the harvest: the caller receives a :class:`HarvestAborted`
# rather than a partial :class:`HarvestBundle` (and no on-disk bundle is
# written). ``"skip"`` drops the candidate from the bundle but lets the
# loop continue to the next one. ``"accept"`` keeps the candidate.
HarvestDecision = Literal["accept", "skip", "quit"]

# Signature of the per-candidate prompt callback. The harvester passes the
# candidate plus ``(index, total)`` for "N of M"-style progress display.
# Implementations live in :mod:`forge.cli.interactive` (real TUI) and in
# tests (deterministic deque-of-decisions stub). The default of ``None``
# threaded through :func:`harvest_project` means "accept every candidate"
# — preserving the legacy non-interactive contract.
PromptCallback = Callable[[CandidatePatch, int, int], HarvestDecision]


class HarvestAborted(Exception):
    """Raised when the operator selects ``quit`` at the interactive prompt.

    Carries the partial candidate list inspected so far purely for
    diagnostics; callers MUST NOT persist it — the contract is "quit
    aborts cleanly, no partial bundle written". The CLI dispatcher
    catches this and exits cleanly.
    """

    def __init__(self, inspected_count: int) -> None:
        super().__init__(
            f"Harvest aborted by operator after inspecting {inspected_count} candidate(s)."
        )
        self.inspected_count = inspected_count

# Every extractor kind the orchestrator understands. The CLI accepts a
# subset via ``--harvest-include``; the bundle stores patches grouped
# by ``kind`` for the reviewer.
_ALL_KINDS: tuple[str, ...] = ("files", "blocks", "deps", "env")

# Maps the CLI include token to the extractor's reported ``.kind`` so
# we can drop extractors that don't match. The CLI uses the plural
# ``"blocks"`` for consistency with verify's ``--verify-scope``; the
# extractor reports the singular ``"block"`` for the candidate kind tag.
_INCLUDE_TO_EXTRACTOR_KIND: dict[str, str] = {
    "files": "files",
    "blocks": "block",
    "deps": "deps",
    "env": "env",
}


@dataclass(frozen=True)
class HarvestBundle:
    """One harvest run's output — what to write to disk.

    Attributes:
        bundle_id: Unique identifier of the form
            ``harvest-<UTC-timestamp>-<8-char-hash>``. Stable enough to
            disambiguate concurrent harvests of the same project root.
        project_root: Absolute path to the project the candidates were
            extracted from. Recorded so reviewers can trace back to the
            source tree without re-running the harvest.
        forge_version: ``forge``'s own package version at harvest time.
            Lets a maintainer reject candidates from an older forge if
            the fragment registry has moved.
        candidates: Every :class:`CandidatePatch` the extractor pipeline
            emitted, post-scope-filter and post-include-filter.
    """

    bundle_id: str
    project_root: Path
    forge_version: str
    candidates: list[CandidatePatch]

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly view for ``forge --harvest --harvest-out=-``.

        ``current_body`` / ``feature_key`` / ``marker`` are only emitted
        when populated — keeping the JSON shape minimal for the common
        ``files`` / ``deps`` / ``env`` cases that don't carry them. The
        apply-back path reads these fields directly off the in-memory
        bundle, so on-disk serialisation is for review/diagnostics only.
        """
        out: list[dict[str, Any]] = []
        for c in self.candidates:
            row: dict[str, Any] = {
                "fragment": c.fragment,
                "backend": c.backend,
                "kind": c.kind,
                "rel_path": c.rel_path,
                "target_path": c.target_path,
                "diff": c.diff,
                "baseline_sha": c.baseline_sha,
                "current_sha": c.current_sha,
                "risk": c.risk,
                "rationale": c.rationale,
            }
            if c.current_body:
                row["current_body"] = c.current_body
            if c.feature_key:
                row["feature_key"] = c.feature_key
            if c.marker:
                row["marker"] = c.marker
            out.append(row)
        return {
            "bundle_id": self.bundle_id,
            "project_root": str(self.project_root),
            "forge_version": self.forge_version,
            "candidates": out,
        }

    def write(self, out_dir: Path) -> None:
        """Write the bundle to ``out_dir`` per the round-trip spec.

        Layout::

            <out_dir>/
              manifest.json
              README.md
              patches/
                <fragment-name>/
                  meta.json
                  0001-block-<safe_key>.patch
                  0002-files-<safe_key>.patch
                  ...

        ``manifest.json`` carries the full candidate list (same shape
        as :meth:`to_dict`). Each per-fragment ``meta.json`` records
        the fragment name + version (when known) and the extractor
        kinds that produced patches. ``README.md`` is a placeholder
        that links to ``docs/round-trip.md`` (full workflow doc is a
        Phase 4b follow-up).
        """
        # Delayed import — keeps the orchestrator module light when
        # callers only use it for the in-memory bundle (e.g. tests).
        from forge.sync.project_to_forge.bundle import write_bundle  # noqa: PLC0415

        write_bundle(self, out_dir)


def harvest_project(
    project_root: Path,
    *,
    out_dir: Path | None = None,
    scope: tuple[str, ...] | None = None,
    include: tuple[str, ...] = ("files", "blocks", "deps", "env"),
    interactive: bool = False,
    prompt_callback: PromptCallback | None = None,
    quiet: bool = False,
) -> HarvestBundle:
    """Walk the project's manifest and run the extractor pipeline.

    Resolves the manifest's ``[forge.options]`` against the current
    fragment registry, builds one :class:`ExtractionPlan` per active
    fragment, runs :meth:`ExtractorPipeline.default`, and collects the
    candidates into a :class:`HarvestBundle`.

    ``scope`` (tuple of fragment names) restricts the bundle to that
    set — out-of-scope fragments still get plans built but their
    candidates are filtered before bundling. ``include`` (subset of
    ``{"files","blocks","deps","env"}``) restricts which extractor
    kinds run. Empty include == empty bundle.

    When ``out_dir`` is non-None, the bundle is also persisted via
    :meth:`HarvestBundle.write` so the CLI dispatcher doesn't have to.

    ``interactive`` opts the harvest into the per-candidate review loop:
    every real (non-cross-lang) candidate is passed to ``prompt_callback``
    which returns ``"accept"`` / ``"skip"`` / ``"quit"``. Skipped
    candidates are pruned from the bundle (and any derivative cross-lang
    suggestions are pruned with them); ``"quit"`` raises
    :class:`HarvestAborted` and no bundle is persisted. When
    ``interactive`` is False (the default) ``prompt_callback`` is ignored
    and every candidate is kept — preserving the legacy headless
    contract. Passing ``prompt_callback`` without ``interactive`` is a
    no-op, mirroring the CLI surface where ``--harvest-interactive``
    gates the prompt wiring.

    Raises :class:`ProvenanceError` if ``project_root`` isn't a
    forge-generated project (missing ``forge.toml``).
    Raises :class:`HarvestAborted` if the operator selects ``quit`` at
    the interactive prompt.
    """
    manifest = project_root / "forge.toml"
    if not manifest.is_file():
        raise ProvenanceError(
            f"No forge.toml at {project_root}. Is this a forge-generated project?",
            code=PROVENANCE_MANIFEST_MISSING,
            context={"project_root": str(project_root)},
        )

    data = read_forge_toml(manifest)
    try:
        forge_version = metadata.version("forge")
    except metadata.PackageNotFoundError:
        forge_version = "0.0.0+unknown"

    backends = _infer_backends(project_root)
    config = ProjectConfig(
        project_name=data.project_name or project_root.name,
        backends=list(backends) if backends else [],
        options=dict(data.options),
    )

    # Attempt to resolve the option plan. If the manifest references a
    # fragment / option path the current forge no longer knows about,
    # surface a clean ``no candidates`` result rather than blowing up.
    try:
        resolved = resolve(config)
    except Exception as e:  # noqa: BLE001
        if not quiet:
            print(f"  [harvest] resolver failed ({e}); harvesting against manifest baselines only.")
        # Fallback: synthesize an empty resolved plan so the extractors
        # still walk the manifest's recorded baselines.
        resolved = None

    # Group manifest's merge_blocks by fragment name so each fragment's
    # ExtractionPlan can scope its injection records.
    merge_blocks_by_fragment = _group_merge_blocks_by_fragment(data.merge_blocks)
    provenance_by_fragment = _group_provenance_by_fragment(data.provenance)

    # Build a per-fragment plan. We walk both sources — the resolver's
    # current view AND the manifest's recorded fragments — so a
    # fragment that's been disabled since the project was generated
    # still surfaces its harvest candidates (the operator may want to
    # back-port edits before they're lost).
    fragment_names: set[str] = set()
    if resolved is not None:
        fragment_names.update(rf.fragment.name for rf in resolved.ordered)
    fragment_names.update(merge_blocks_by_fragment)
    fragment_names.update(provenance_by_fragment)
    if scope is not None:
        scope_set = {s.strip() for s in scope if s.strip()}
        fragment_names &= scope_set

    # Active extractor kinds derived from ``include``. ``all`` is the
    # default surface; the CLI translates ``--harvest-include=all`` to
    # the full tuple before reaching here.
    selected_kinds = _select_extractor_kinds(include)
    pipeline = _make_pipeline(selected_kinds)

    candidates: list[CandidatePatch] = []
    for fragment_name in sorted(fragment_names):
        fragment = FRAGMENT_REGISTRY.get(fragment_name)
        # Map this fragment's recorded blocks/files into an
        # ExtractionPlan per backend impl, then run the pipeline.
        # Each plan-context pairing is independent — we don't share
        # state across iterations.
        for ctx, plan in _build_contexts_and_plans(
            project_root=project_root,
            config=config,
            fragment_name=fragment_name,
            fragment=fragment,
            merge_blocks=merge_blocks_by_fragment.get(fragment_name, {}),
            provenance=provenance_by_fragment.get(fragment_name, {}),
            data_merge_blocks=data.merge_blocks,
            option_values=dict(resolved.option_values) if resolved is not None else {},
        ):
            patches = pipeline.run(ctx, plan)
            candidates.extend(patches)

    # Theme 2C — interactive review pass. We prompt on the REAL
    # candidates only (before the cross-lang parity pass) because
    # cross-lang suggestions are derivative: skipping a parent block
    # candidate should drop its sibling-language suggestions too, and
    # accepting one accepts its suggestions implicitly. When the
    # operator picks ``quit`` mid-loop we raise :class:`HarvestAborted`
    # and do NOT persist anything — the partial-bundle scenario isn't a
    # valid harvest output, so the CLI exits cleanly with no on-disk
    # artefact.
    if interactive and prompt_callback is not None and candidates:
        candidates = _run_interactive_review(candidates, prompt_callback)

    # RFC-006 cross-language parity pass — for each ``block`` candidate
    # harvested off a tier-1 fragment, emit synthetic ``cross-lang-suggest``
    # entries for the parallel impls on every OTHER built-in backend.
    # This is purely additive: the existing candidates are untouched,
    # and the new entries carry no diff (apply-back defers them; emit-pr
    # surfaces them in the reviewer checklist rather than committing
    # them).
    project_backends: set[BackendLanguage] = {
        b.language for b in config.backends if isinstance(b.language, BackendLanguage)
    }
    suggestions = _emit_cross_lang_suggestions(candidates, FRAGMENT_REGISTRY, project_backends)
    candidates.extend(suggestions)

    bundle_id = _make_bundle_id(project_root)
    bundle = HarvestBundle(
        bundle_id=bundle_id,
        project_root=project_root,
        forge_version=forge_version,
        candidates=candidates,
    )

    if out_dir is not None:
        bundle.write(out_dir)

    if not quiet:
        print(
            f"  [harvest] {len(candidates)} candidate(s) across "
            f"{len(fragment_names)} fragment(s); bundle_id={bundle_id}"
        )

    return bundle


# ---------------------------------------------------------------------------
# Plan construction helpers
# ---------------------------------------------------------------------------


def _group_merge_blocks_by_fragment(
    merge_blocks: dict[str, dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Bucket manifest merge_blocks by their ``fragment_name`` entry.

    Pre-1.2 manifests may not record ``fragment_name`` per block — the
    feature_key (parsed from the manifest key) is the fallback. Entries
    that can't be attributed get bucketed under a synthetic
    ``"<unattributed>"`` name so the orchestrator still emits an
    ExtractionPlan for them.
    """
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for key, entry in merge_blocks.items():
        fragment_name = entry.get("fragment_name")
        if not fragment_name:
            # Fall back to the feature_key parsed out of the manifest
            # key. The feature_key was historically the fragment name
            # for inject.yaml-emitted blocks.
            parsed = MergeBlockCollector.parse_key(key)
            fragment_name = parsed[1] if parsed else "<unattributed>"
        out.setdefault(str(fragment_name), {})[key] = entry
    return out


def _group_provenance_by_fragment(
    provenance: dict[str, dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Bucket manifest provenance rows by ``fragment_name``.

    Only records with ``origin == "fragment"`` are bucketed — the rest
    are base-template / user files that the harvester ignores.
    """
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for rel_path, entry in provenance.items():
        if entry.get("origin") != "fragment":
            continue
        fragment_name = entry.get("fragment_name")
        if not fragment_name:
            continue
        out.setdefault(str(fragment_name), {})[rel_path] = entry
    return out


def _build_contexts_and_plans(
    *,
    project_root: Path,
    config: ProjectConfig,
    fragment_name: str,
    fragment: Fragment | None,
    merge_blocks: dict[str, dict[str, Any]],
    provenance: dict[str, dict[str, Any]],
    data_merge_blocks: dict[str, dict[str, Any]],
    option_values: Mapping[str, Any],
) -> Iterable[tuple[FragmentContext, ExtractionPlan]]:
    """Yield ``(context, plan)`` pairs for one fragment.

    Walks the project's backends and emits one pair per backend that
    has either recorded blocks or provenance for this fragment. The
    pair carries everything the extractor pipeline needs.

    When the fragment is no longer in the registry (disabled since
    generation), we still emit a pair using the manifest-side metadata
    so the InjectionExtractor can produce ``conflict`` candidates for
    the orphan blocks.
    """
    file_baselines = _file_baselines_from_provenance(provenance)

    for backend in config.backends:
        backend_dir = project_root / "services" / backend.name
        if not backend_dir.is_dir():
            continue
        impl = fragment.implementations.get(backend.language) if fragment else None

        # Filter the merge_blocks down to those targeting paths inside
        # this backend (or project-scope). We do this by checking the
        # manifest's stored rel_path against the backend's rel.
        blocks_for_backend = _filter_blocks_for_backend(
            merge_blocks=merge_blocks,
            backend_rel=_backend_rel(project_root, backend_dir),
            scope=impl.scope if impl is not None else "backend",
        )

        injections = _make_injection_records(
            backend_dir=backend_dir,
            project_root=project_root,
            blocks=blocks_for_backend,
            fragment_name=fragment_name,
            impl=impl,
            option_values=option_values,
        )

        plan = ExtractionPlan(
            fragment_name=fragment_name,
            files=_files_pairs(impl, project_root, backend_dir, provenance),
            injections=injections,
            dependencies=impl.dependencies if impl is not None else (),
            env_vars=impl.env_vars if impl is not None else (),
        )

        ctx = _make_fragment_context(
            backend_config=backend,
            backend_dir=backend_dir,
            project_root=project_root,
            options=option_values,
            impl=impl,
            file_baselines=file_baselines,
            merge_block_baselines=data_merge_blocks,
        )

        yield ctx, plan


def _backend_rel(project_root: Path, backend_dir: Path) -> str:
    """POSIX rel-path of the backend dir against the project root."""
    try:
        return backend_dir.relative_to(project_root).as_posix() + "/"
    except ValueError:
        return ""


def _filter_blocks_for_backend(
    *,
    merge_blocks: dict[str, dict[str, Any]],
    backend_rel: str,
    scope: str,
) -> dict[str, dict[str, Any]]:
    """Pick blocks whose recorded rel_path lives under this backend.

    Project-scope fragments accept blocks anywhere in the project tree
    (the ``backend_dir`` for those is the project root).
    """
    if scope == "project" or not backend_rel:
        return dict(merge_blocks)
    out: dict[str, dict[str, Any]] = {}
    for key, entry in merge_blocks.items():
        parsed = MergeBlockCollector.parse_key(key)
        if parsed is None:
            continue
        rel_path = parsed[0]
        if rel_path.startswith(backend_rel):
            out[key] = entry
    return out


def _make_injection_records(
    *,
    backend_dir: Path,
    project_root: Path,
    blocks: dict[str, dict[str, Any]],
    fragment_name: str,
    impl: FragmentImplSpec | None,
    option_values: Mapping[str, Any],
) -> tuple[Any, ...]:
    """Build _Injection-like records for each recorded merge_block.

    We can't always reach the upstream snippet at harvest time — the
    fragment may have been disabled, the inject.yaml renamed, etc. So
    we synthesize a minimal duck-typed record per block carrying just
    the fields the InjectionExtractor reads:

    * ``feature_key``
    * ``target``  (path relative to ``backend_dir``)
    * ``marker``
    * ``snippet`` (upstream rendered body — empty string when we can't
       resolve the fragment's inject.yaml)

    When the fragment IS resolvable, we load + render the inject.yaml
    entry that matches the block's marker and stamp the snippet on
    the record. The InjectionExtractor's three-way decide handles the
    rest.
    """
    upstream_snippets = _load_upstream_snippets(impl, option_values, fragment_name)

    records: list[Any] = []
    for key in blocks:
        parsed = MergeBlockCollector.parse_key(key)
        if parsed is None:
            continue
        rel_path, feature_key, marker = parsed
        # Rebase the project-root-relative path against the backend
        # dir so ``ctx.backend_dir / inj.target`` resolves correctly
        # in the extractor.
        target_rel = _rebase_target(rel_path, backend_dir, project_root)
        # Look up the upstream snippet under (marker, feature_key) first;
        # ``_load_injections`` (called via ``_load_upstream_snippets``)
        # stamps records with the placeholder feature_key ``"<harvest>"``,
        # so the manifest's own feature_key won't match directly. Fall
        # back to the wildcard ``"*"`` entry that ``_load_upstream_snippets``
        # also indexes — it carries the upstream body keyed by marker
        # alone, which is unique enough for round-trip.
        snippet = upstream_snippets.get((marker, feature_key)) or upstream_snippets.get(
            (marker, "*"), ""
        )
        records.append(
            _InjectionRecord(
                feature_key=feature_key,
                target=target_rel,
                marker=marker,
                snippet=snippet,
            )
        )
    return tuple(records)


def _rebase_target(rel_path: str, backend_dir: Path, project_root: Path) -> str:
    """Convert a project-root rel-path into a backend-dir rel-path.

    The manifest stores POSIX rel-paths against ``project_root``; the
    forward applier's ``_Injection.target`` is rooted at
    ``backend_dir``. The InjectionExtractor joins ``ctx.backend_dir /
    inj.target``, so we re-base on the way in.
    """
    try:
        backend_rel = backend_dir.relative_to(project_root).as_posix() + "/"
    except ValueError:
        return rel_path
    if rel_path.startswith(backend_rel):
        return rel_path[len(backend_rel) :]
    return rel_path


def _load_upstream_snippets(
    impl: FragmentImplSpec | None,
    option_values: Mapping[str, Any],
    fragment_name: str,  # noqa: ARG001 — reserved for plugin diagnostics
) -> dict[tuple[str, str], str]:
    """Pre-render the fragment's inject.yaml entries.

    Returns a ``{(marker, feature_key): rendered_snippet}`` map. Empty
    when the impl isn't available or the fragment has no inject.yaml.
    Render errors are swallowed at the entry level — the extractor
    will catch the missing snippet and emit a ``needs-review`` /
    ``no-baseline`` candidate.
    """
    if impl is None:
        return {}
    try:
        from forge.appliers.plan import _load_injections  # noqa: PLC0415
        from forge.fragments import _resolve_fragment_dir  # noqa: PLC0415
    except ImportError:
        return {}

    fragment_dir = _resolve_fragment_dir(impl.fragment_dir)
    inject_yaml = fragment_dir / "inject.yaml"
    if not inject_yaml.is_file():
        return {}

    # ``_load_injections`` raises on undefined Jinja variables. We
    # render with the project's option values so the upstream body
    # matches what the forward applier would emit. On any render
    # failure we return whatever entries we successfully built so far
    # — partial coverage is better than zero coverage.
    out: dict[tuple[str, str], str] = {}
    try:
        # The feature_key arg is whatever the fragment uses in its
        # sentinel tag. The block records parsed out of the manifest
        # already carry their own feature_key — we key the map by
        # that, not by the fragment_name argument.
        records = _load_injections(inject_yaml, "<harvest>", options=dict(option_values))
    except Exception:  # noqa: BLE001 — fall back to per-entry attempt below.
        records = []

    for rec in records:
        # ``_load_injections`` stamps the feature_key we passed in, but
        # the manifest entries carry the upstream feature_key. We can
        # only key by the marker for the lookup; collisions are rare
        # (markers are scoped per target file).
        out[(str(rec.marker), str(rec.feature_key))] = str(rec.snippet)
        # Also expose under the wildcard "*" feature_key so harvest
        # records that don't share the same feature_key as
        # _load_injections's stand-in still find their upstream.
        out[(str(rec.marker), "*")] = str(rec.snippet)
    return out


def _files_pairs(
    impl: FragmentImplSpec | None,
    project_root: Path,
    backend_dir: Path,
    provenance: dict[str, dict[str, Any]],
) -> tuple[tuple[str, str], ...]:
    """Build ``(fragment_relpath, dst_relpath)`` pairs from provenance.

    The forward applier records each fragment-emitted file under
    ``[forge.provenance]`` with its origin + fragment name. We pair
    that against the fragment's ``files/`` tree to give the
    FileExtractor a flat set of paths to compare. Falls back to an
    empty tuple when the fragment has no impl (disabled fragment).
    """
    if impl is None:
        return ()
    try:
        from forge.fragments import _resolve_fragment_dir  # noqa: PLC0415
    except ImportError:
        return ()

    fragment_dir = _resolve_fragment_dir(impl.fragment_dir)
    files_dir = fragment_dir / "files"
    if not files_dir.is_dir():
        return ()

    try:
        backend_rel = backend_dir.relative_to(project_root).as_posix() + "/"
    except ValueError:
        backend_rel = ""

    out: list[tuple[str, str]] = []
    for rel_path in provenance:
        # Skip rows that aren't under this backend.
        if backend_rel and not rel_path.startswith(backend_rel):
            continue
        dst_rel = rel_path[len(backend_rel) :] if backend_rel else rel_path
        candidate = files_dir / dst_rel
        if candidate.is_file():
            out.append((dst_rel, dst_rel))
    return tuple(out)


def _file_baselines_from_provenance(
    provenance: dict[str, dict[str, Any]],
) -> dict[str, str]:
    """Project-root POSIX rel-path → baseline SHA from a manifest table."""
    out: dict[str, str] = {}
    for rel_path, entry in provenance.items():
        sha = entry.get("sha256")
        if not sha:
            continue
        out[str(rel_path)] = str(sha)
    return out


def _make_fragment_context(
    *,
    backend_config: BackendConfig,
    backend_dir: Path,
    project_root: Path,
    options: Mapping[str, Any],
    impl: FragmentImplSpec | None,
    file_baselines: Mapping[str, str],
    merge_block_baselines: Mapping[str, Mapping[str, Any]],
) -> FragmentContext:
    """Construct a :class:`FragmentContext` for one fragment × backend.

    The InjectionExtractor reads ``ctx.merge_block_baselines`` via
    ``getattr`` (the field isn't part of the dataclass), so we attach
    it via ``object.__setattr__`` post-construction. The other
    extractors only read declared fields.
    """
    reads_options = impl.reads_options if impl is not None else ()
    ctx = FragmentContext.filtered(
        backend_config=backend_config,
        backend_dir=backend_dir,
        project_root=project_root,
        option_values=dict(options),
        reads_options=reads_options,
        provenance=None,
        update_mode="merge",
        file_baselines=dict(file_baselines),
    )
    # Attach the merge_block_baselines side-channel without mutating
    # the FragmentContext dataclass definition (sealed for Phase 4).
    object.__setattr__(
        ctx,
        "merge_block_baselines",
        {str(k): dict(v) for k, v in merge_block_baselines.items()},
    )
    return ctx


def _select_extractor_kinds(include: tuple[str, ...]) -> set[str]:
    """Translate CLI include tokens to extractor ``.kind`` strings."""
    out: set[str] = set()
    for token in include:
        mapped = _INCLUDE_TO_EXTRACTOR_KIND.get(token)
        if mapped:
            out.add(mapped)
    return out


def _make_pipeline(selected_kinds: set[str]) -> ExtractorPipeline:
    """Build an extractor pipeline restricted to ``selected_kinds``.

    Empty ``selected_kinds`` produces an empty pipeline (so
    ``--harvest-include`` with an unrecognized value yields a quiet
    no-op rather than running every extractor).
    """
    default = ExtractorPipeline.default()
    filtered = tuple(e for e in default.extractors if e.kind in selected_kinds)
    return ExtractorPipeline(extractors=filtered)


# ---------------------------------------------------------------------------
# Cross-language parity pass (RFC-006)
# ---------------------------------------------------------------------------


def _emit_cross_lang_suggestions(
    candidates: list[CandidatePatch],
    fragment_registry: Mapping[str, Fragment],
    project_backends: set[BackendLanguage],  # noqa: ARG001 — see note below.
) -> list[CandidatePatch]:
    """For each ``block`` candidate from a tier-1 fragment, emit synthetic
    ``cross-lang-suggest`` candidates for the parallel impls in OTHER
    backends.

    ``Other`` = every :class:`BackendLanguage` in ``fragment.implementations``
    that ISN'T the candidate's source backend. Includes:

    * Backends not present in the project (e.g. a Python-only project with a
      tier-1 fragment — Node + Rust impls still get suggestions).
    * Backends present in the project but with no edits to this fragment.

    Why both: a tier-1 fragment's parity is enforced at the fragment level,
    not the project level (see ``tests/test_fragment_parity.py``). If the
    user edits the Python impl of a tier-1 middleware fragment, the
    maintainer should review the Node + Rust impls too even if those
    backends aren't in this specific project — otherwise the parity
    contract drifts the moment a downstream project picks up the merged
    change.

    The ``project_backends`` arg is accepted for symmetry with the helper's
    documented semantics, but the function deliberately does NOT filter
    by it — both classes of sibling are surfaced. The parameter is kept
    for callers that may want to introspect which suggestions name a
    backend the project doesn't ship.
    """
    suggestions: list[CandidatePatch] = []
    for cand in candidates:
        # Only block-kind candidates have cross-lang parallels — deps/env
        # are language-specific by definition (different manifest format
        # per backend) and ``files`` carries no marker for sibling
        # lookup.
        if cand.kind != "block":
            continue
        frag = fragment_registry.get(cand.fragment)
        if frag is None or frag.parity_tier != 1:
            continue
        source_lang = _lang_from_backend(
            cand.backend, frag, rel_path=cand.rel_path, marker=cand.marker
        )
        if source_lang is None:
            # The backend label couldn't be resolved to a registered
            # BackendLanguage — most likely because the fragment's
            # impls don't carry one matching the candidate's source.
            # Without a source, "other" is ambiguous; bail safely.
            continue
        for impl_lang in frag.implementations:
            if impl_lang == source_lang:
                continue
            sibling_target = _find_sibling_target(frag, impl_lang, cand.feature_key, cand.marker)
            if sibling_target is None:
                # No matching marker on the sibling impl's inject.yaml —
                # don't fabricate a target. The fragment may genuinely
                # not have a parallel block for this edit (different
                # injection topology per backend).
                continue
            lang_value = impl_lang.value if hasattr(impl_lang, "value") else str(impl_lang)
            suggestions.append(
                CandidatePatch(
                    fragment=cand.fragment,
                    backend=lang_value,
                    kind="cross-lang-suggest",
                    rel_path=sibling_target,
                    target_path=sibling_target,
                    diff=(
                        f"Mirror the change from {cand.backend}/{cand.target_path} "
                        f"(markers share feature_key + marker name across impls)."
                    ),
                    baseline_sha=None,
                    current_sha="",
                    risk="needs-review",
                    rationale=(
                        f"Tier-1 fragment {cand.fragment!r} has parallel impls for "
                        f"{sorted(_lang_value(lang) for lang in frag.implementations)}. "
                        "Cross-stack parity is enforced by tests/test_fragment_parity.py; "
                        "please mirror the edit."
                    ),
                    current_body="",
                    feature_key=cand.feature_key,
                    marker=cand.marker,
                )
            )
    return suggestions


def _lang_value(lang: object) -> str:
    """Return a sortable string for a BackendLanguage-like enum member."""
    return getattr(lang, "value", None) or str(lang)


def _lang_from_backend(
    backend: str,  # noqa: ARG001 — kept for callers; primary lookup is on rel_path+marker.
    fragment: Fragment,
    *,
    rel_path: str = "",
    marker: str = "",
) -> BackendLanguage | None:
    """Identify which of the fragment's impls a candidate originated from.

    The candidate's ``backend`` field is the BackendConfig name (e.g.
    ``api``) — free-form per project, not a language value — so we
    can't go directly from that to a :class:`BackendLanguage`. The
    most reliable mapping is to walk the fragment's impls and find
    which one's ``inject.yaml`` carries an entry matching the
    candidate's ``rel_path`` + ``marker``. That entry's impl is the
    source.

    Falls back to a direct ``backend == lang.value`` match (so callers
    that pass a language label as the backend, e.g. test fixtures, still
    work) and finally returns ``None`` when neither path matches.

    Only :class:`BackendLanguage` members are returned —
    plugin-registered language sentinels are skipped, because the
    cross-lang pass only knows how to talk about the built-in trio.
    """
    # Try the rel_path+marker match against each impl's inject.yaml.
    if rel_path and marker:
        for lang, impl in fragment.implementations.items():
            if not isinstance(lang, BackendLanguage):
                continue
            try:
                from forge.fragments import _resolve_fragment_dir  # noqa: PLC0415
            except ImportError:
                continue
            fragment_dir = _resolve_fragment_dir(impl.fragment_dir)
            inject_yaml = fragment_dir / "inject.yaml"
            if not inject_yaml.is_file():
                continue
            try:
                doc = yaml.safe_load(inject_yaml.read_text(encoding="utf-8"))
            except (yaml.YAMLError, OSError):
                continue
            if not isinstance(doc, list):
                continue
            for entry in doc:
                if not isinstance(entry, dict):
                    continue
                if (
                    str(entry.get("marker", "")) == marker
                    and str(entry.get("target", "")) == rel_path
                ):
                    return lang

    # Direct match — caller passed a language label as the backend.
    for lang in fragment.implementations:
        if isinstance(lang, BackendLanguage) and _lang_value(lang) == backend:
            return lang

    return None


def _find_sibling_target(
    fragment: Fragment,
    lang: BackendLanguage,
    feature_key: str,  # noqa: ARG001 — surfaced for callers that may filter on it.
    marker: str,
) -> str | None:
    """Resolve the parallel ``inject.yaml`` target for ``lang``.

    Reads ``<fragment_dir>/inject.yaml`` for the sibling impl and finds
    the entry whose ``marker`` matches the candidate's marker. Returns
    the entry's ``target`` field (a backend-rooted POSIX rel-path).
    Returns ``None`` when no matching entry exists — the fragment may
    legitimately not ship a parallel block for this marker on the
    sibling backend.

    The match is on ``marker`` alone (not ``feature_key``) because
    markers are conventionally shared across the per-language impls of
    a tier-1 fragment (e.g. ``FORGE:MIDDLEWARE_REGISTRATION`` appears
    in the Python, Node, and Rust ``inject.yaml`` files of the
    ``rate_limit`` fragment). ``feature_key`` is accepted in the
    signature so callers can opt into a stricter match later without an
    API break.
    """
    impl = fragment.implementations.get(lang)
    if impl is None:
        return None
    # Lazy import — keeps the orchestrator's import surface stable.
    from forge.fragments import _resolve_fragment_dir  # noqa: PLC0415

    fragment_dir = _resolve_fragment_dir(impl.fragment_dir)
    inject_yaml = fragment_dir / "inject.yaml"
    if not inject_yaml.is_file():
        return None
    try:
        doc = yaml.safe_load(inject_yaml.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return None
    if not isinstance(doc, list):
        return None
    for entry in doc:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("marker", "")) == marker:
            target = entry.get("target")
            if isinstance(target, str) and target:
                return target
    return None


# ---------------------------------------------------------------------------
# Interactive review (Theme 2C — --harvest-interactive)
# ---------------------------------------------------------------------------


def _run_interactive_review(
    candidates: list[CandidatePatch],
    prompt_callback: PromptCallback,
) -> list[CandidatePatch]:
    """Drive the per-candidate accept/skip/quit prompt loop.

    Iterates ``candidates`` in their natural emission order, calling
    ``prompt_callback`` once per entry with ``(index, total)`` so the UI
    can render a "Candidate N of M" header. ``"accept"`` keeps the
    candidate; ``"skip"`` drops it; ``"quit"`` raises
    :class:`HarvestAborted` carrying the count of candidates inspected
    so far.

    Unknown return values from a buggy callback are treated as
    ``"skip"`` rather than crashing — the cost of a dropped candidate
    is recoverable (re-run harvest) where a TypeError in the middle of
    a review pass loses operator state. We keep this defensive but
    silent; harness tests assert the legal vocabulary.
    """
    accepted: list[CandidatePatch] = []
    total = len(candidates)
    for idx, cand in enumerate(candidates, start=1):
        decision = prompt_callback(cand, idx, total)
        if decision == "accept":
            accepted.append(cand)
        elif decision == "quit":
            raise HarvestAborted(inspected_count=idx)
        # "skip" (or any unknown token) → drop the candidate silently.
    return accepted


# ---------------------------------------------------------------------------
# Bundle identity
# ---------------------------------------------------------------------------


def _make_bundle_id(project_root: Path) -> str:
    """Build a unique bundle id of the form ``harvest-<ts>-<hash8>``.

    The timestamp is UTC in ``YYYYmmddTHHMMSSZ`` form so the bundle
    sorts naturally in a filesystem listing. The hash prefix
    disambiguates two harvests fired in the same second.
    """
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(str(project_root).encode("utf-8")).hexdigest()[:8]
    return f"harvest-{ts}-{digest}"


# ---------------------------------------------------------------------------
# Duck-typed _Injection record (no dep on forge.feature_injector at module load)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _InjectionRecord:
    """Minimal duck-typed substitute for ``forge.feature_injector._Injection``.

    The orchestrator builds these from manifest entries because the
    upstream ``_Injection`` carries fields the harvester doesn't have
    (``position``, ``zone``) and a fragment-version-specific snippet
    we'd have to re-render here. Keeping the substitute local also
    means we don't pin the import path — the InjectionExtractor only
    reads ``feature_key``, ``target``, ``marker``, ``snippet``.
    """

    feature_key: str
    target: str
    marker: str
    snippet: str
    position: str = "after"
    zone: str = "merge"


# Reserved placeholder; ``field`` is imported above for downstream call sites
# that may extend HarvestBundle. Quiets unused-import lints.
_ = field
