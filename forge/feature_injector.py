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
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
import yaml

from forge.capability_resolver import ResolvedFragment
from forge.config import BackendConfig, BackendLanguage
from forge.errors import (
    FRAGMENT_DEP_SPEC_INVALID,
    FRAGMENT_DEPS_FILE_MISSING,
    FRAGMENT_DEPS_SECTION_MISSING,
    FRAGMENT_FILES_OVERLAP,
    FRAGMENT_INJECT_YAML_BAD_POSITION,
    FRAGMENT_INJECT_YAML_BAD_SHAPE,
    FRAGMENT_INJECT_YAML_BAD_ZONE,
    FRAGMENT_INJECT_YAML_MISSING_KEY,
    INJECTION_MARKER_AMBIGUOUS,
    INJECTION_MARKER_MISSING,
    INJECTION_SENTINEL_CORRUPT,
    INJECTION_TARGET_MISSING,
    FragmentError,
    InjectionError,
)
from forge.fragment_context import FragmentContext
from forge.fragments import FRAGMENTS_DIRNAME, MARKER_PREFIX, FragmentImplSpec
from forge.middleware_spec import MiddlewareSpec
from forge.provenance import ProvenanceCollector

TEMPLATES_DIR = Path(__file__).parent / "templates"
FRAGMENTS_DIR = TEMPLATES_DIR / FRAGMENTS_DIRNAME


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


# File-extension → single-line comment prefix. Only line-comment forms are
# supported (never `/* */` or `<!-- -->`); in practice every injection
# target in the forge registry is a .py / .ts / .rs file.
_COMMENT_PREFIXES: dict[str, str] = {
    ".py": "#",
    ".pyi": "#",
    ".yml": "#",
    ".yaml": "#",
    ".toml": "#",
    ".env": "#",
    ".sh": "#",
    ".ts": "//",
    ".tsx": "//",
    ".js": "//",
    ".jsx": "//",
    ".mjs": "//",
    ".cjs": "//",
    ".rs": "//",
    ".go": "//",
}


def _comment_prefix(file: Path) -> str:
    """Comment-syntax prefix for BEGIN/END sentinels.

    Unknown extensions fall back to ``#``. If you add a fragment that
    injects into a new file type, register its prefix here rather than
    relying on the fallback — sentinel mismatches break idempotency.
    """
    return _COMMENT_PREFIXES.get(file.suffix.lower(), "#")


def _sentinel_tag(feature_key: str, marker: str) -> str:
    """Tag identifying one injection. Unique per (file, feature, marker)."""
    # Strip FORGE: prefix from marker so the tag reads naturally.
    naked = marker[len(MARKER_PREFIX) :] if marker.startswith(MARKER_PREFIX) else marker
    return f"{feature_key}:{naked}"


def apply_features(
    bc: BackendConfig,
    backend_dir: Path,
    resolved: tuple[ResolvedFragment, ...],
    quiet: bool = False,
    *,
    skip_existing_files: bool = False,
    collector: ProvenanceCollector | None = None,
    option_values: Mapping[str, Any] | None = None,
    project_root: Path | None = None,
) -> None:
    """Apply each backend-scoped fragment that supports this backend.

    Project-scoped fragments are emitted separately via
    ``apply_project_features`` after all backends are rendered.

    When ``skip_existing_files=True`` (used by ``forge --update``), a
    fragment's ``files/`` copy-phase skips files that already exist
    instead of raising. Lets repeated applies be idempotent without
    clobbering user edits.

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
            skip_existing_files=skip_existing_files,
        )
        _apply_fragment(ctx, impl, rf.fragment.name, middlewares=rf.fragment.middlewares)


def apply_project_features(
    project_root: Path,
    resolved: tuple[ResolvedFragment, ...],
    quiet: bool = False,
    *,
    skip_existing_files: bool = False,
    collector: ProvenanceCollector | None = None,
    option_values: Mapping[str, Any] | None = None,
) -> None:
    """Apply project-scoped fragment implementations at the project root.

    See :func:`apply_features` for ``option_values`` semantics.
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
                    skip_existing_files=skip_existing_files,
                )
                # Project-scope fragments typically don't declare middlewares
                # (they emit project-level files like AGENTS.md). Pass the
                # tuple anyway so the pipeline API stays uniform.
                _apply_fragment(
                    ctx, impl, rf.fragment.name, middlewares=rf.fragment.middlewares
                )
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
    doesn't need to know pipelines exist. A future PR moves the
    applier-helper bodies (``_copy_files``, ``_add_dependencies``, etc.)
    out of this module and into the applier modules that own them.
    """
    from forge.appliers import FragmentPipeline  # noqa: PLC0415

    FragmentPipeline.default().run(ctx, impl, feature_key, middlewares=middlewares)


# -- File copy ---------------------------------------------------------------


def _copy_files(
    src: Path,
    dst_root: Path,
    *,
    skip_existing: bool = False,
    collector: ProvenanceCollector | None = None,
    fragment_name: str | None = None,
) -> None:
    """Copy every file under src/ into dst_root/, preserving structure.

    On fresh generation (default), refuses to overwrite existing files —
    fragments must not clobber the base template silently. If you need to
    modify an existing file, use inject.yaml.

    On ``forge update`` (``skip_existing=True``), pre-existing destination
    paths are left alone and logged; this preserves user edits while still
    letting newly-introduced fragment files land.

    When ``collector`` is supplied, every newly-written file records its
    provenance with ``origin='fragment'`` and the given ``fragment_name``.
    """
    for src_path in src.rglob("*"):
        if not src_path.is_file():
            continue
        rel = src_path.relative_to(src)
        dst_path = dst_root / rel
        if dst_path.exists():
            if skip_existing:
                continue
            raise FragmentError(
                f"Fragment '{src.parent.name}' tried to overwrite existing file "
                f"'{dst_path}'. Use inject.yaml to modify existing files; "
                "fragments/files/ is for new paths only.",
                code=FRAGMENT_FILES_OVERLAP,
                context={"fragment": src.parent.name, "destination": str(dst_path)},
            )
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)
        if collector is not None:
            collector.record(dst_path, origin="fragment", fragment_name=fragment_name)


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
        return _apply_merge_zone(
            target, inj, project_root=project_root, collector=collector
        )

    _dispatch_injector(target, inj)
    # For merge-zone on first apply (no baseline), record the block so
    # the next re-apply can three-way-merge. This also covers the
    # project_root-is-None fallback path when merge can't run.
    if inj.zone == "merge" and collector is not None and project_root is not None:
        _record_merge_baseline(
            target, inj, project_root=project_root, collector=collector
        )
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
            _record_merge_baseline(
                target, inj, project_root=project_root, collector=collector
            )
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
            _record_merge_baseline(
                target, inj, project_root=project_root, collector=collector
            )
        return True

    if decision in ("skipped-no-change", "skipped-idempotent"):
        return False

    # decision == "conflict"
    tag = _sentinel_tag(inj.feature_key, inj.marker)
    write_sidecar(target, new_body, tag)
    return False


def _read_block_body(file: Path, feature_key: str, marker: str) -> str | None:
    """Return the lines between BEGIN/END sentinels for this tag, exclusive."""
    if not file.is_file():
        return None
    tag = _sentinel_tag(feature_key, marker)
    begin_needle = f"{MARKER_PREFIX}BEGIN {tag}"
    end_needle = f"{MARKER_PREFIX}END {tag}"
    text = file.read_text(encoding="utf-8")
    if begin_needle not in text or end_needle not in text:
        return None
    lines = text.splitlines(keepends=True)
    begin_idx = next((i for i, line in enumerate(lines) if begin_needle in line), None)
    end_idx = next((i for i, line in enumerate(lines) if end_needle in line), None)
    if begin_idx is None or end_idx is None or end_idx <= begin_idx:
        return None
    return "".join(lines[begin_idx + 1 : end_idx])


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


def _has_sentinel_block(file: Path, feature_key: str, marker: str) -> bool:
    """True when ``file`` already contains a BEGIN/END sentinel pair for this tag."""
    if not file.is_file():
        return False
    tag = _sentinel_tag(feature_key, marker)
    begin_needle = f"{MARKER_PREFIX}BEGIN {tag}"
    end_needle = f"{MARKER_PREFIX}END {tag}"
    text = file.read_text(encoding="utf-8")
    return begin_needle in text and end_needle in text


def _inject_snippet(
    file: Path,
    feature_key: str,
    marker: str,
    snippet: str,
    position: str,
) -> None:
    """Insert or replace ``snippet`` at a ``# FORGE:<marker>`` site.

    The injection is wrapped in BEGIN / END sentinel comments keyed to
    ``feature_key:marker_name``. Running this twice on the same file replaces
    the existing block in place rather than duplicating — the foundation
    of ``forge update`` idempotency (see B2.4 plan).

    Rules:
      - Marker (the ``# FORGE:<marker>`` line) must appear exactly once.
      - If a BEGIN/END pair with this tag exists, replace the block (lines
        between the two sentinels, inclusive).
      - Otherwise, emit ``BEGIN, <snippet lines>, END`` at the marker
        position (``before`` → above the marker; ``after`` → below).
      - Indentation is inherited from the marker line and applied to the
        sentinel + snippet lines so the block slots into the enclosing
        scope cleanly.
    """
    if not file.is_file():
        raise InjectionError(
            f"Injection target not found: {file}",
            code=INJECTION_TARGET_MISSING,
            context={"file": str(file)},
        )

    needle = marker if marker.startswith(MARKER_PREFIX) else f"{MARKER_PREFIX}{marker}"
    prefix = _comment_prefix(file)
    tag = _sentinel_tag(feature_key, marker)
    begin_needle = f"{MARKER_PREFIX}BEGIN {tag}"
    end_needle = f"{MARKER_PREFIX}END {tag}"

    text = file.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # Path 1 — sentinel block already present → replace in place.
    begin_idx = _find_unique_line(lines, begin_needle, file, needle=begin_needle)
    if begin_idx is not None:
        end_idx = _find_unique_line(lines, end_needle, file, needle=end_needle)
        if end_idx is None or end_idx < begin_idx:
            raise InjectionError(
                f"{file}: found BEGIN sentinel for '{tag}' but matching END "
                f"is missing or out of order.",
                code=INJECTION_SENTINEL_CORRUPT,
                context={"file": str(file), "tag": tag},
            )
        # Preserve the BEGIN line's indentation so a regenerated block keeps
        # the same shape as the original marker-aligned one.
        indent = _indent_of(lines[begin_idx])
        fresh = _render_block(indent, prefix, tag, snippet)
        lines = lines[:begin_idx] + [fresh] + lines[end_idx + 1 :]
        file.write_text("".join(lines), encoding="utf-8")
        return

    # Path 2 — fresh injection: find the marker and insert a new block.
    marker_idx = _find_unique_line(lines, needle, file, needle=needle)
    if marker_idx is None:
        raise InjectionError(
            f"Marker '{needle}' not found in {file}. "
            "Add the marker to the base template or check the fragment's inject.yaml.",
            code=INJECTION_MARKER_MISSING,
            context={"file": str(file), "marker": needle},
        )
    indent = _indent_of(lines[marker_idx])
    block = _render_block(indent, prefix, tag, snippet)

    insert_at = marker_idx + 1 if position == "after" else marker_idx
    lines = lines[:insert_at] + [block] + lines[insert_at:]
    file.write_text("".join(lines), encoding="utf-8")


def _find_unique_line(lines: list[str], substring: str, file: Path, *, needle: str) -> int | None:
    """Return the unique line index containing ``substring`` or None.

    Raises if the substring appears more than once — ambiguous sentinels
    would silently corrupt re-injection.
    """
    hits = [i for i, line in enumerate(lines) if substring in line]
    if not hits:
        return None
    if len(hits) > 1:
        raise InjectionError(
            f"'{needle}' appears {len(hits)} times in {file}; must be unique.",
            code=INJECTION_MARKER_AMBIGUOUS,
            context={"file": str(file), "marker": needle, "count": len(hits)},
        )
    return hits[0]


def _indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def _render_block(indent: str, prefix: str, tag: str, snippet: str) -> str:
    """Produce ``{indent}{prefix} BEGIN ...\\n<snippet>\\n{indent}{prefix} END ...\\n``."""
    begin = f"{indent}{prefix} {MARKER_PREFIX}BEGIN {tag}\n"
    end = f"{indent}{prefix} {MARKER_PREFIX}END {tag}\n"
    body = "".join(f"{indent}{line}\n" for line in snippet.splitlines())
    return begin + body + end


# -- Dependency addition -----------------------------------------------------


def _add_dependencies(lang: BackendLanguage, backend_dir: Path, deps: tuple[str, ...]) -> None:
    if not deps:
        return
    if lang is BackendLanguage.PYTHON:
        _add_python_deps(backend_dir / "pyproject.toml", deps)
    elif lang is BackendLanguage.NODE:
        _add_node_deps(backend_dir / "package.json", deps)
    elif lang is BackendLanguage.RUST:
        _add_rust_deps(backend_dir / "Cargo.toml", deps)


def _add_python_deps(pyproject: Path, deps: tuple[str, ...]) -> None:
    if not pyproject.is_file():
        raise FragmentError(
            f"pyproject.toml not found at {pyproject}",
            code=FRAGMENT_DEPS_FILE_MISSING,
            context={"path": str(pyproject), "language": "python"},
        )
    doc = tomlkit.parse(pyproject.read_text(encoding="utf-8"))
    project = doc.get("project")
    if project is None:
        raise FragmentError(
            f"{pyproject}: [project] section missing",
            code=FRAGMENT_DEPS_SECTION_MISSING,
            context={"path": str(pyproject), "section": "project"},
        )
    existing = list(project.get("dependencies", []))
    existing_names = {_py_dep_name(d): d for d in existing}
    for dep in deps:
        name = _py_dep_name(dep)
        if name in existing_names:
            continue
        existing.append(dep)
        existing_names[name] = dep
    project["dependencies"] = existing
    pyproject.write_text(tomlkit.dumps(doc), encoding="utf-8")


def _py_dep_name(dep: str) -> str:
    """Extract the package name from a PEP 508 spec like `slowapi>=0.1.9`."""
    for sep in ("==", ">=", "<=", "~=", "!=", ">", "<", "["):
        if sep in dep:
            return dep.split(sep, 1)[0].strip().lower()
    return dep.strip().lower()


def _add_node_deps(package_json: Path, deps: tuple[str, ...]) -> None:
    if not package_json.is_file():
        raise FragmentError(
            f"package.json not found at {package_json}",
            code=FRAGMENT_DEPS_FILE_MISSING,
            context={"path": str(package_json), "language": "node"},
        )
    raw = package_json.read_text(encoding="utf-8")
    data = json.loads(raw)
    deps_obj: dict[str, Any] = data.setdefault("dependencies", {})
    for dep in deps:
        # Node dep spec: "name@version" or "name" for latest.
        if "@" in dep and not dep.startswith("@"):
            name, version = dep.split("@", 1)
        elif dep.startswith("@"):
            # Scoped package like "@fastify/rate-limit@1.2.3"
            head, _, tail = dep[1:].partition("@")
            if tail:
                name, version = "@" + head, tail
            else:
                name, version = dep, "latest"
        else:
            name, version = dep, "latest"
        if name not in deps_obj:
            deps_obj[name] = version
    package_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _add_rust_deps(cargo_toml: Path, deps: tuple[str, ...]) -> None:
    """Merge Cargo dependencies. Two forms supported:

    - Shorthand: ``"name@version"`` → ``name = "version"``.
    - Full TOML: ``'name = { version = "x", features = [...] }'`` →
      parsed verbatim so features / git / default-features work.

    Existing entries are preserved — forge never clobbers hand-edited deps.
    """
    if not cargo_toml.is_file():
        raise FragmentError(
            f"Cargo.toml not found at {cargo_toml}",
            code=FRAGMENT_DEPS_FILE_MISSING,
            context={"path": str(cargo_toml), "language": "rust"},
        )
    doc = tomlkit.parse(cargo_toml.read_text(encoding="utf-8"))
    table = doc.setdefault("dependencies", tomlkit.table())
    for dep in deps:
        name, value = _parse_rust_dep(dep)
        if name not in table:
            table[name] = value
    cargo_toml.write_text(tomlkit.dumps(doc), encoding="utf-8")


def _parse_rust_dep(dep: str) -> tuple[str, Any]:
    """Parse a Cargo dep spec into ``(name, value)`` where value is either a
    version string or a tomlkit-parsed inline table.

    >>> _parse_rust_dep("tower@0.5")
    ('tower', '0.5')
    >>> _parse_rust_dep('opentelemetry-otlp = { version = "0.27", features = ["grpc-tonic"] }')  # doctest: +ELLIPSIS
    ('opentelemetry-otlp', ...)
    """
    stripped = dep.strip()
    # Full-form check: "name = <toml>" — detected by a top-level ``=`` outside
    # of the shorthand's ``@`` separator. We prefer ``=`` when present.
    if "=" in stripped and not _is_at_shorthand(stripped):
        name_part, _, rhs = stripped.partition("=")
        name = name_part.strip()
        if not name:
            raise FragmentError(
                f"bad Rust dep spec (empty name): {dep!r}",
                code=FRAGMENT_DEP_SPEC_INVALID,
                context={"dep": dep, "reason": "empty_name"},
            )
        try:
            parsed = tomlkit.parse(f"__v = {rhs.strip()}")
        except Exception as e:  # noqa: BLE001
            raise FragmentError(
                f"bad Rust dep value in {dep!r}: {e}",
                code=FRAGMENT_DEP_SPEC_INVALID,
                context={"dep": dep, "reason": "toml_parse_failure"},
            ) from e
        return name, parsed["__v"]
    if "@" in stripped:
        name, version = stripped.split("@", 1)
        return name.strip(), version.strip()
    return stripped, "*"


def _is_at_shorthand(dep: str) -> bool:
    """True if `dep` looks like ``name@version`` — no ``=`` before the ``@``."""
    if "@" not in dep:
        return False
    at = dep.index("@")
    eq = dep.find("=")
    return eq == -1 or eq > at


# -- Env vars ----------------------------------------------------------------


def _add_env_var(env_file: Path, key: str, value: str) -> None:
    """Append KEY=VALUE to env_file unless KEY already present."""
    line = f"{key}={value}\n"
    if env_file.is_file():
        existing = env_file.read_text(encoding="utf-8")
        # Match KEY= at start of any line (idempotent).
        for row in existing.splitlines():
            if row.startswith(f"{key}="):
                return
        if not existing.endswith("\n"):
            existing += "\n"
        env_file.write_text(existing + line, encoding="utf-8")
    else:
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text(line, encoding="utf-8")
