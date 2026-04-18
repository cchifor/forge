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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
import yaml

from forge.capability_resolver import ResolvedFeature
from forge.config import BackendConfig, BackendLanguage
from forge.errors import GeneratorError
from forge.features import FRAGMENTS_DIRNAME, MARKER_PREFIX, FragmentImplSpec

TEMPLATES_DIR = Path(__file__).parent / "templates"
FRAGMENTS_DIR = TEMPLATES_DIR / FRAGMENTS_DIRNAME


@dataclass(frozen=True)
class _Injection:
    feature_key: str  # the owning FeatureSpec.key, used in BEGIN/END sentinels
    target: str  # path relative to backend_dir
    marker: str  # e.g. "FORGE:MIDDLEWARE_REGISTRATION"
    snippet: str
    # "after" (default) places snippet on the line after the marker;
    # "before" on the line before. Marker line is preserved either way.
    position: str = "after"


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
    resolved: tuple[ResolvedFeature, ...],
    quiet: bool = False,
    *,
    skip_existing_files: bool = False,
) -> None:
    """Apply each enabled *backend-scoped* feature that supports this backend.

    Project-scoped features are emitted separately via `apply_project_features`
    after all backends are rendered.

    When ``skip_existing_files=True`` (used by ``forge update``), a fragment's
    ``files/`` copy-phase skips files that already exist instead of raising.
    This lets repeated applies be idempotent without clobbering user edits.
    """
    for feature in resolved:
        if bc.language not in feature.target_backends:
            continue
        impl = feature.spec.implementations[bc.language]
        if impl.scope != "backend":
            continue
        if not quiet:
            print(f"  [feat] applying '{feature.spec.key}' to {bc.name} ({bc.language.value})")
        _apply_fragment(
            bc,
            backend_dir,
            impl,
            feature.config.options,
            feature.spec.key,
            skip_existing_files=skip_existing_files,
        )


def apply_project_features(
    project_root: Path,
    resolved: tuple[ResolvedFeature, ...],
    quiet: bool = False,
    *,
    skip_existing_files: bool = False,
) -> None:
    """Apply project-scoped implementations at the project root.

    Chooses a canonical backend to use for per-language dep edits (the first
    target_backend for the feature). For pure-file fragments (like AGENTS.md)
    the backend choice is irrelevant.

    ``skip_existing_files`` is forwarded to the ``_copy_files`` step so the
    updater can re-run project-scope fragments without clobbering edits.
    """
    for feature in resolved:
        # Pick any supporting implementation with scope=project.
        for lang in feature.target_backends:
            impl = feature.spec.implementations[lang]
            if impl.scope == "project":
                if not quiet:
                    print(f"  [feat] applying '{feature.spec.key}' to project root")
                proxy = BackendConfig(name="project", project_name="", language=lang)
                _apply_fragment(
                    proxy,
                    project_root,
                    impl,
                    feature.config.options,
                    feature.spec.key,
                    skip_existing_files=skip_existing_files,
                )
                break  # one emission only, even if multiple backends support it


def _apply_fragment(
    bc: BackendConfig,
    backend_dir: Path,
    impl: FragmentImplSpec,
    options: dict[str, Any],
    feature_key: str,
    *,
    skip_existing_files: bool = False,
) -> None:
    fragment = FRAGMENTS_DIR / impl.fragment_dir
    if not fragment.is_dir():
        raise GeneratorError(
            f"Fragment directory not found: {fragment}. "
            "Check FragmentImplSpec.fragment_dir in features.py."
        )

    files_dir = fragment / "files"
    if files_dir.is_dir():
        _copy_files(files_dir, backend_dir, skip_existing=skip_existing_files)

    inject_path = fragment / "inject.yaml"
    if inject_path.is_file():
        for inj in _load_injections(inject_path, feature_key):
            _inject_snippet(
                backend_dir / inj.target,
                inj.feature_key,
                inj.marker,
                inj.snippet,
                inj.position,
            )

    # Dependencies come from the FragmentImplSpec (static) OR from deps.yaml
    # (which can vary by option — kept simple in v1: static only).
    if impl.dependencies:
        _add_dependencies(bc.language, backend_dir, impl.dependencies)

    if impl.env_vars:
        env_file = backend_dir / ".env.example"
        for key, value in impl.env_vars:
            _add_env_var(env_file, key, value)


# -- File copy ---------------------------------------------------------------


def _copy_files(src: Path, dst_root: Path, *, skip_existing: bool = False) -> None:
    """Copy every file under src/ into dst_root/, preserving structure.

    On fresh generation (default), refuses to overwrite existing files —
    fragments must not clobber the base template silently. If you need to
    modify an existing file, use inject.yaml.

    On ``forge update`` (``skip_existing=True``), pre-existing destination
    paths are left alone and logged; this preserves user edits while still
    letting newly-introduced fragment files land.
    """
    for src_path in src.rglob("*"):
        if not src_path.is_file():
            continue
        rel = src_path.relative_to(src)
        dst_path = dst_root / rel
        if dst_path.exists():
            if skip_existing:
                continue
            raise GeneratorError(
                f"Fragment '{src.parent.name}' tried to overwrite existing file "
                f"'{dst_path}'. Use inject.yaml to modify existing files; "
                "fragments/files/ is for new paths only."
            )
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)


# -- Snippet injection -------------------------------------------------------


def _load_injections(path: Path, feature_key: str) -> list[_Injection]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(data, list):
        raise GeneratorError(
            f"{path}: expected a YAML list of injections, got {type(data).__name__}"
        )
    out: list[_Injection] = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise GeneratorError(f"{path}[{i}]: injection must be a mapping")
        try:
            target = str(entry["target"])
            marker = str(entry["marker"])
            snippet = str(entry["snippet"])
        except KeyError as e:
            raise GeneratorError(f"{path}[{i}]: missing required key {e}") from e
        position = str(entry.get("position", "after"))
        if position not in ("before", "after"):
            raise GeneratorError(f"{path}[{i}]: position must be 'before' or 'after'")
        out.append(
            _Injection(
                feature_key=feature_key,
                target=target,
                marker=marker,
                snippet=snippet,
                position=position,
            )
        )
    return out


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
        raise GeneratorError(f"Injection target not found: {file}")

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
            raise GeneratorError(
                f"{file}: found BEGIN sentinel for '{tag}' but matching END "
                f"is missing or out of order."
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
        raise GeneratorError(
            f"Marker '{needle}' not found in {file}. "
            "Add the marker to the base template or check the fragment's inject.yaml."
        )
    indent = _indent_of(lines[marker_idx])
    block = _render_block(indent, prefix, tag, snippet)

    insert_at = marker_idx + 1 if position == "after" else marker_idx
    lines = lines[:insert_at] + [block] + lines[insert_at:]
    file.write_text("".join(lines), encoding="utf-8")


def _find_unique_line(
    lines: list[str], substring: str, file: Path, *, needle: str
) -> int | None:
    """Return the unique line index containing ``substring`` or None.

    Raises if the substring appears more than once — ambiguous sentinels
    would silently corrupt re-injection.
    """
    hits = [i for i, line in enumerate(lines) if substring in line]
    if not hits:
        return None
    if len(hits) > 1:
        raise GeneratorError(
            f"'{needle}' appears {len(hits)} times in {file}; must be unique."
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
        raise GeneratorError(f"pyproject.toml not found at {pyproject}")
    doc = tomlkit.parse(pyproject.read_text(encoding="utf-8"))
    project = doc.get("project")
    if project is None:
        raise GeneratorError(f"{pyproject}: [project] section missing")
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
        raise GeneratorError(f"package.json not found at {package_json}")
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
        raise GeneratorError(f"Cargo.toml not found at {cargo_toml}")
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
            raise GeneratorError(f"bad Rust dep spec (empty name): {dep!r}")
        try:
            parsed = tomlkit.parse(f"__v = {rhs.strip()}")
        except Exception as e:  # noqa: BLE001
            raise GeneratorError(f"bad Rust dep value in {dep!r}: {e}") from e
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
