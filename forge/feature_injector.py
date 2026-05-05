"""Apply resolved features to a generated backend directory.

Fragments do four kinds of mutations:
    1. Copy verbatim files from `<fragment>/files/` into the backend.
    2. Inject source snippets at ``# FORGE:NAME`` markers (strict — missing
       marker raises).
    3. Add language-specific dependencies (pyproject.toml via tomlkit,
       package.json via dict merge, Cargo.toml via tomlkit).
    4. Append env vars to .env.example idempotently.

Each fragment directory ships an ``inject.yaml``, ``deps.yaml``, and
``env.yaml`` describing what to do. All three are optional; a pure-copy
fragment can omit them entirely. A fragment with zero files and no yaml is
valid — it just registers presence in forge.toml without touching the project.

P1.1 (Epic 1b) split this module: sentinel primitives moved into
:mod:`forge.injectors.sentinels`, deps logic into
:mod:`forge.appliers.deps`. The names are re-exported here for one
minor as backward-compat for callers that imported them from this
module before the split.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from forge.appliers.deps import (
    _add_dependencies,
    _add_node_deps,
    _add_python_deps,
    _add_rust_deps,
    _is_at_shorthand,
    _parse_rust_dep,
    _py_dep_name,
)
from forge.appliers.env import append_env_var as _add_env_var
from forge.capability_resolver import ResolvedFragment
from forge.config import BackendConfig
from forge.errors import (
    FRAGMENT_INJECT_YAML_BAD_POSITION,
    FRAGMENT_INJECT_YAML_BAD_SHAPE,
    FRAGMENT_INJECT_YAML_BAD_ZONE,
    FRAGMENT_INJECT_YAML_MISSING_KEY,
    FragmentError,
)
from forge.fragment_context import FragmentContext, UpdateMode
from forge.fragments import FRAGMENTS_DIRNAME, MARKER_PREFIX, FragmentImplSpec
from forge.injectors.sentinels import (
    _COMMENT_PREFIXES,
    _comment_prefix,
    _find_unique_line,
    _has_sentinel_block,
    _indent_of,
    _inject_snippet,
    _read_block_body,
    _render_block,
    _sentinel_tag,
)
from forge.middleware_spec import MiddlewareSpec
from forge.provenance import ProvenanceCollector

TEMPLATES_DIR = Path(__file__).parent / "templates"
FRAGMENTS_DIR = TEMPLATES_DIR / FRAGMENTS_DIRNAME

# Re-exports (backward compat — see module docstring).
__all__ = [
    # Public API
    "FRAGMENTS_DIR",
    "MARKER_PREFIX",
    "TEMPLATES_DIR",
    "apply_features",
    "apply_project_features",
    # Backward-compat re-exports of items that moved in P1.1 (Epic 1b)
    "_COMMENT_PREFIXES",
    "_Injection",
    "_add_dependencies",
    "_add_env_var",
    "_add_node_deps",
    "_add_python_deps",
    "_add_rust_deps",
    "_apply_fragment",
    "_apply_merge_zone",
    "_apply_zoned_injection",
    "_comment_prefix",
    "_copy_files",
    "_dispatch_injector",
    "_find_unique_line",
    "_has_sentinel_block",
    "_indent_of",
    "_inject_snippet",
    "_is_at_shorthand",
    "_load_injections",
    "_load_merge_baseline",
    "_parse_rust_dep",
    "_py_dep_name",
    "_read_block_body",
    "_record_merge_baseline",
    "_render_block",
    "_render_snippet",
    "_resolve_fragment_dir",
    "_sentinel_tag",
]


def _resolve_fragment_dir(fragment_dir: str) -> Path:
    """Resolve a fragment's directory path.

    Relative paths are interpreted relative to forge's ``_fragments/``
    directory (the canonical location for built-in fragments). Absolute
    paths are used verbatim — this is the path plugins take: they ship
    fragments inside their own package tree and pass
    ``str(Path(__file__).parent / "fragments" / "my_thing")``.

    Plugin authors who want the automatic resolution can wrap their
    fragment directory in a helper like:

        from pathlib import Path
        MY_FRAGMENT_ROOT = Path(__file__).resolve().parent / "fragments"
        spec = FragmentImplSpec(fragment_dir=str(MY_FRAGMENT_ROOT / "audit_log/python"))
    """
    path = Path(fragment_dir)
    if path.is_absolute():
        return path
    return FRAGMENTS_DIR / fragment_dir


@dataclass(frozen=True)
class _Injection:
    feature_key: str  # the owning FeatureSpec.key, used in BEGIN/END sentinels
    target: str  # path relative to backend_dir
    marker: str  # e.g. "FORGE:MIDDLEWARE_REGISTRATION"
    snippet: str
    # "after" (default) places snippet on the line after the marker;
    # "before" on the line before. Marker line is preserved either way.
    position: str = "after"
    # Zone determines the idempotent-reapply semantics for this injection:
    #   * "generated" — default; re-generation overwrites (current behavior).
    #   * "user"      — emit on first apply; subsequent `forge --update`
    #                   passes leave the block untouched even if the
    #                   fragment snippet has changed. Use for sections the
    #                   user is expected to customize after generation.
    #   * "merge"     — attempt a three-way merge against the provenance
    #                   baseline. On conflict, emit `.forge-merge` markers
    #                   and return non-zero from update. Requires a
    #                   non-empty provenance entry for the target file.
    zone: str = "generated"


def apply_features(
    bc: BackendConfig,
    backend_dir: Path,
    resolved: tuple[ResolvedFragment, ...],
    quiet: bool = False,
    *,
    update_mode: UpdateMode = "strict",
    file_baselines: Mapping[str, str] | None = None,
    collector: ProvenanceCollector | None = None,
    option_values: Mapping[str, Any] | None = None,
    project_root: Path | None = None,
) -> None:
    """Apply each backend-scoped fragment that supports this backend.

    Project-scoped fragments are emitted separately via
    ``apply_project_features`` after all backends are rendered.

    ``update_mode`` (P0.1, 1.1.0-alpha.2) drives the file-copy collision
    behaviour. ``"strict"`` is fresh generation — fragments may not
    overlap the base template or each other. ``"merge"`` / ``"skip"`` /
    ``"overwrite"`` are the three ``forge --update`` modes; see
    :data:`forge.fragment_context.UpdateMode`.

    ``file_baselines`` is the manifest's per-file baseline SHA map
    (POSIX rel-path → SHA-256). Required by ``"merge"`` mode for the
    three-way decision; ignored by the other modes.

    When ``collector`` is supplied, every file written by the fragment
    layer is recorded in the provenance manifest with ``origin='fragment'``
    and the fragment's name.

    ``option_values`` (Epic E, 1.1.0-alpha.1) — the resolver's fully-
    defaulted option map. When provided, each fragment's
    :class:`FragmentContext` sees a filtered view restricted to the
    impl's ``reads_options`` tuple. When omitted (backward-compat for
    callers that haven't threaded the plan through yet), fragments see
    ``ctx.options == {}`` — the pre-Epic-E behaviour.

    ``project_root`` is needed for merge-zone injections and future
    provenance-driven uninstall. Defaults to ``backend_dir.parent.parent``
    on the assumption of the conventional ``<project_root>/services/<backend>/``
    layout — the generator always passes it explicitly.
    """
    if option_values is None:
        option_values = {}
    if project_root is None:
        project_root = backend_dir.parent.parent
    for rf in resolved:
        if bc.language not in rf.target_backends:
            continue
        impl = rf.fragment.implementations[bc.language]
        if impl.scope != "backend":
            continue
        if not quiet:
            print(f"  [frag] applying '{rf.fragment.name}' to {bc.name} ({bc.language.value})")
        ctx = FragmentContext.filtered(
            backend_config=bc,
            backend_dir=backend_dir,
            project_root=project_root,
            option_values=option_values,
            reads_options=impl.reads_options,
            provenance=collector,
            update_mode=update_mode,
            file_baselines=file_baselines,
        )
        _apply_fragment(ctx, impl, rf.fragment.name, middlewares=rf.fragment.middlewares)


def apply_project_features(
    project_root: Path,
    resolved: tuple[ResolvedFragment, ...],
    quiet: bool = False,
    *,
    update_mode: UpdateMode = "strict",
    file_baselines: Mapping[str, str] | None = None,
    collector: ProvenanceCollector | None = None,
    option_values: Mapping[str, Any] | None = None,
) -> None:
    """Apply project-scoped fragment implementations at the project root.

    See :func:`apply_features` for ``update_mode``, ``file_baselines``,
    and ``option_values`` semantics.
    """
    if option_values is None:
        option_values = {}
    for rf in resolved:
        for lang in rf.target_backends:
            impl = rf.fragment.implementations[lang]
            if impl.scope == "project":
                if not quiet:
                    print(f"  [frag] applying '{rf.fragment.name}' to project root")
                proxy = BackendConfig(name="project", project_name="", language=lang)
                ctx = FragmentContext.filtered(
                    backend_config=proxy,
                    backend_dir=project_root,
                    project_root=project_root,
                    option_values=option_values,
                    reads_options=impl.reads_options,
                    provenance=collector,
                    update_mode=update_mode,
                    file_baselines=file_baselines,
                )
                # Project-scope fragments typically don't declare middlewares
                # (they emit project-level files like AGENTS.md). Pass the
                # tuple anyway so the pipeline API stays uniform.
                _apply_fragment(ctx, impl, rf.fragment.name, middlewares=rf.fragment.middlewares)
                break


def _apply_fragment(
    ctx: FragmentContext,
    impl: FragmentImplSpec,
    feature_key: str,
    *,
    middlewares: tuple[MiddlewareSpec, ...] = (),
) -> None:
    """Apply one fragment implementation via the default :class:`FragmentPipeline`.

    Epic A lands the applier decomposition: four single-responsibility
    classes composed by :class:`FragmentPipeline`. Epic K threads any
    :class:`MiddlewareSpec` declarations on the fragment into the plan
    so the applier emits the middleware import + registration lines
    without a handwritten ``inject.yaml``.

    This function is a stable internal entry point — callers inside
    ``feature_injector`` route through it so the rest of the module
    doesn't need to know pipelines exist.
    """
    from forge.appliers import FragmentPipeline  # noqa: PLC0415

    FragmentPipeline.default().run(ctx, impl, feature_key, middlewares=middlewares)


# -- File copy ---------------------------------------------------------------
# The body moved to :mod:`forge.appliers.files` in P0.1 (1.1.0-alpha.2).
# Kept as a thin shim translating the legacy ``skip_existing`` boolean to
# the new ``update_mode`` enum so external callers (mostly tests, but
# possibly third-party plugins) keep working through one minor before
# the shim is removed.


def _copy_files(
    src: Path,
    dst_root: Path,
    *,
    skip_existing: bool = False,
    collector: ProvenanceCollector | None = None,
    fragment_name: str | None = None,
) -> None:
    """Deprecated. Use :func:`forge.appliers.files.copy_files`.

    ``skip_existing=True`` maps to ``update_mode="skip"``,
    ``skip_existing=False`` maps to ``update_mode="strict"`` (the
    pre-1.1 raise-on-overlap default). Scheduled removal: 2.0.
    """
    import warnings  # noqa: PLC0415

    from forge.appliers.files import copy_files  # noqa: PLC0415

    warnings.warn(
        "forge.feature_injector._copy_files is deprecated (since 1.1.0a2). "
        "Use forge.appliers.files.copy_files with update_mode= "
        "(strict|skip|merge|overwrite). Scheduled removal: 2.0.",
        DeprecationWarning,
        stacklevel=2,
    )
    copy_files(
        src,
        dst_root,
        update_mode="skip" if skip_existing else "strict",
        collector=collector,
        fragment_name=fragment_name,
    )


# -- Snippet injection -------------------------------------------------------


def _render_snippet(snippet: str, options: Mapping[str, Any]) -> str:
    """Jinja-render a snippet with ``options`` as the template context.

    Opt-in per-injection via ``render: true`` in ``inject.yaml``. Undeclared
    variables raise — a typo in ``{{ rag.top_k }}`` should not silently
    inject an empty string. ``StrictUndefined`` handles this.
    """
    import jinja2  # noqa: PLC0415 — lazy so pure-copy fragments don't pay the import

    env = jinja2.Environment(
        autoescape=False,
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
    )
    try:
        return env.from_string(snippet).render(options=dict(options), **dict(options))
    except jinja2.UndefinedError as e:
        raise FragmentError(
            f"inject.yaml snippet renders an undefined variable: {e}. "
            f"Declare the option path in FragmentImplSpec.reads_options so "
            f"the resolver can validate it at resolve time.",
            code=FRAGMENT_INJECT_YAML_BAD_SHAPE,
            context={"undefined_error": str(e)},
        ) from e


def _load_injections(
    path: Path,
    feature_key: str,
    *,
    options: Mapping[str, Any] | None = None,
) -> list[_Injection]:
    """Parse ``inject.yaml`` into typed :class:`_Injection` records.

    Epic E adds optional Jinja rendering of the ``snippet`` field. When a
    YAML entry sets ``render: true`` and ``options`` is non-empty, the
    snippet is Jinja-rendered with ``options`` in scope before injection.
    Fragments that don't need templating (most of them) leave ``render``
    unset and the snippet is used verbatim.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(data, list):
        raise FragmentError(
            f"{path}: expected a YAML list of injections, got {type(data).__name__}",
            code=FRAGMENT_INJECT_YAML_BAD_SHAPE,
            context={"path": str(path), "got_type": type(data).__name__},
        )
    out: list[_Injection] = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise FragmentError(
                f"{path}[{i}]: injection must be a mapping",
                code=FRAGMENT_INJECT_YAML_BAD_SHAPE,
                context={"path": str(path), "index": i},
            )
        try:
            target = str(entry["target"])
            marker = str(entry["marker"])
            snippet = str(entry["snippet"])
        except KeyError as e:
            raise FragmentError(
                f"{path}[{i}]: missing required key {e}",
                code=FRAGMENT_INJECT_YAML_MISSING_KEY,
                context={"path": str(path), "index": i, "missing_key": str(e).strip("'")},
            ) from e
        if entry.get("render"):
            snippet = _render_snippet(snippet, options or {})
        position = str(entry.get("position", "after"))
        if position not in ("before", "after"):
            raise FragmentError(
                f"{path}[{i}]: position must be 'before' or 'after'",
                code=FRAGMENT_INJECT_YAML_BAD_POSITION,
                context={"path": str(path), "index": i, "position": position},
            )
        zone = str(entry.get("zone", "generated"))
        if zone not in ("generated", "user", "merge"):
            raise FragmentError(
                f"{path}[{i}]: zone must be 'generated' | 'user' | 'merge' (got {zone!r})",
                code=FRAGMENT_INJECT_YAML_BAD_ZONE,
                context={"path": str(path), "index": i, "zone": zone},
            )
        out.append(
            _Injection(
                feature_key=feature_key,
                target=target,
                marker=marker,
                snippet=snippet,
                position=position,
                zone=zone,
            )
        )
    return out


# -- Zone dispatch -----------------------------------------------------------


def _apply_zoned_injection(
    target: Path,
    inj: _Injection,
    *,
    project_root: Path | None = None,
    collector: ProvenanceCollector | None = None,
) -> bool:
    """Dispatch an injection according to its zone.

    Returns ``True`` when the injection was applied (the target file's
    content has changed), ``False`` when the zone semantics kept the
    existing content. Callers use the return value to decide whether to
    record a provenance update.

    Zone semantics (1.0.0a3+):
      * ``generated`` — always apply; replace any existing sentinel block.
      * ``user``      — apply only if no sentinel block for this tag
                        already exists. If a block is present, leave it
                        alone (the user may have customized its body).
      * ``merge``     — three-way merge against the provenance baseline
                        in ``forge.toml``'s ``[forge.merge_blocks]``
                        table. Emits ``.forge-merge`` sidecar on
                        conflict; leaves the target untouched. See
                        ``forge/merge.py``.
    """
    if inj.zone == "user" and _has_sentinel_block(target, inj.feature_key, inj.marker):
        return False

    if inj.zone == "merge" and project_root is not None:
        return _apply_merge_zone(target, inj, project_root=project_root, collector=collector)

    _dispatch_injector(target, inj)
    # For merge-zone on first apply (no baseline), record the block so
    # the next re-apply can three-way-merge. This also covers the
    # project_root-is-None fallback path when merge can't run.
    if inj.zone == "merge" and collector is not None and project_root is not None:
        _record_merge_baseline(target, inj, project_root=project_root, collector=collector)
    return True


def _apply_merge_zone(
    target: Path,
    inj: _Injection,
    *,
    project_root: Path,
    collector: ProvenanceCollector | None,
) -> bool:
    """Three-way merge path for ``merge``-zone injections."""
    from forge.merge import MergeBlockCollector, three_way_decide, write_sidecar  # noqa: PLC0415

    try:
        rel_path = target.relative_to(project_root).as_posix()
    except ValueError:
        rel_path = target.as_posix()

    key = MergeBlockCollector.key_for(rel_path, inj.feature_key, inj.marker)
    baseline_sha = _load_merge_baseline(project_root, key)

    if not _has_sentinel_block(target, inj.feature_key, inj.marker):
        # First apply — no sentinel block yet. Behave like generated and
        # record the baseline.
        _dispatch_injector(target, inj)
        if collector is not None:
            _record_merge_baseline(target, inj, project_root=project_root, collector=collector)
        return True

    current_body = _read_block_body(target, inj.feature_key, inj.marker) or ""
    new_body = inj.snippet

    decision = three_way_decide(
        baseline_sha=baseline_sha,
        current_body=current_body,
        new_body=new_body,
    )

    if decision in ("no-baseline", "applied"):
        _dispatch_injector(target, inj)
        if collector is not None:
            _record_merge_baseline(target, inj, project_root=project_root, collector=collector)
        return True

    if decision in ("skipped-no-change", "skipped-idempotent"):
        return False

    # decision == "conflict"
    tag = _sentinel_tag(inj.feature_key, inj.marker)
    write_sidecar(target, new_body, tag)
    return False


def _record_merge_baseline(
    target: Path,
    inj: _Injection,
    *,
    project_root: Path,
    collector: ProvenanceCollector,
) -> None:
    """Record the SHA of the block we just wrote — baseline for next compare."""
    from forge.merge import sha256_of_text  # noqa: PLC0415

    body = _read_block_body(target, inj.feature_key, inj.marker)
    if body is None:
        return
    try:
        rel = target.relative_to(project_root).as_posix()
    except ValueError:
        rel = target.as_posix()
    collector.record_merge_block(
        rel_posix_path=rel,
        feature_key=inj.feature_key,
        marker=inj.marker,
        block_sha=sha256_of_text(body),
    )


def _load_merge_baseline(project_root: Path, key: str) -> str | None:
    """Read a baseline sha from ``forge.toml`` if present."""
    manifest = project_root / "forge.toml"
    if not manifest.is_file():
        return None
    try:
        from forge.forge_toml import read_forge_toml  # noqa: PLC0415

        data = read_forge_toml(manifest)
    except Exception:  # noqa: BLE001
        return None
    entry = data.merge_blocks.get(key)
    if not entry:
        return None
    sha = entry.get("sha256")
    return str(sha) if sha else None


def _dispatch_injector(target: Path, inj: _Injection) -> None:
    """Route an injection to the right backend based on the target's extension.

    Python (``.py``) goes through the LibCST-backed injector; TypeScript /
    JavaScript (``.ts`` / ``.tsx`` / ``.js`` / ``.jsx`` / ``.mjs``) through
    the regex-based TS injector. Everything else (``.rs``, ``.toml``,
    ``.yaml``) falls back to the legacy text-marker injector.
    """
    suffix = target.suffix.lower()
    if suffix in (".py", ".pyi"):
        from forge.injectors.python_ast import inject_python  # noqa: PLC0415

        inject_python(target, inj.feature_key, inj.marker, inj.snippet, inj.position)
        return
    if suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        from forge.injectors.ts_ast import inject_ts  # noqa: PLC0415

        inject_ts(target, inj.feature_key, inj.marker, inj.snippet, inj.position)
        return
    _inject_snippet(target, inj.feature_key, inj.marker, inj.snippet, inj.position)
