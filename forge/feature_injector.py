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
    target: str  # path relative to backend_dir
    marker: str  # e.g. "FORGE:MIDDLEWARE_REGISTRATION"
    snippet: str
    # "after" (default) places snippet on the line after the marker;
    # "before" on the line before. Marker line is preserved either way.
    position: str = "after"


def apply_features(
    bc: BackendConfig,
    backend_dir: Path,
    resolved: tuple[ResolvedFeature, ...],
    quiet: bool = False,
) -> None:
    """Apply each enabled *backend-scoped* feature that supports this backend.

    Project-scoped features are emitted separately via `apply_project_features`
    after all backends are rendered.
    """
    for feature in resolved:
        if bc.language not in feature.target_backends:
            continue
        impl = feature.spec.implementations[bc.language]
        if impl.scope != "backend":
            continue
        if not quiet:
            print(f"  [feat] applying '{feature.spec.key}' to {bc.name} ({bc.language.value})")
        _apply_fragment(bc, backend_dir, impl, feature.config.options)


def apply_project_features(
    project_root: Path,
    resolved: tuple[ResolvedFeature, ...],
    quiet: bool = False,
) -> None:
    """Apply project-scoped implementations at the project root.

    Chooses a canonical backend to use for per-language dep edits (the first
    target_backend for the feature). For pure-file fragments (like AGENTS.md)
    the backend choice is irrelevant.
    """
    for feature in resolved:
        # Pick any supporting implementation with scope=project.
        for lang in feature.target_backends:
            impl = feature.spec.implementations[lang]
            if impl.scope == "project":
                if not quiet:
                    print(f"  [feat] applying '{feature.spec.key}' to project root")
                proxy = BackendConfig(name="project", project_name="", language=lang)
                _apply_fragment(proxy, project_root, impl, feature.config.options)
                break  # one emission only, even if multiple backends support it


def _apply_fragment(
    bc: BackendConfig,
    backend_dir: Path,
    impl: FragmentImplSpec,
    options: dict[str, Any],
) -> None:
    fragment = FRAGMENTS_DIR / impl.fragment_dir
    if not fragment.is_dir():
        raise GeneratorError(
            f"Fragment directory not found: {fragment}. "
            "Check FragmentImplSpec.fragment_dir in features.py."
        )

    files_dir = fragment / "files"
    if files_dir.is_dir():
        _copy_files(files_dir, backend_dir)

    inject_path = fragment / "inject.yaml"
    if inject_path.is_file():
        for inj in _load_injections(inject_path):
            _inject_snippet(backend_dir / inj.target, inj.marker, inj.snippet, inj.position)

    # Dependencies come from the FragmentImplSpec (static) OR from deps.yaml
    # (which can vary by option — kept simple in v1: static only).
    if impl.dependencies:
        _add_dependencies(bc.language, backend_dir, impl.dependencies)

    if impl.env_vars:
        env_file = backend_dir / ".env.example"
        for key, value in impl.env_vars:
            _add_env_var(env_file, key, value)


# -- File copy ---------------------------------------------------------------


def _copy_files(src: Path, dst_root: Path) -> None:
    """Copy every file under src/ into dst_root/, preserving structure.

    Refuses to overwrite existing files — fragments must not clobber the base
    template silently. If you need to modify an existing file, use inject.yaml.
    """
    for src_path in src.rglob("*"):
        if not src_path.is_file():
            continue
        rel = src_path.relative_to(src)
        dst_path = dst_root / rel
        if dst_path.exists():
            raise GeneratorError(
                f"Fragment '{src.parent.name}' tried to overwrite existing file "
                f"'{dst_path}'. Use inject.yaml to modify existing files; "
                "fragments/files/ is for new paths only."
            )
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)


# -- Snippet injection -------------------------------------------------------


def _load_injections(path: Path) -> list[_Injection]:
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
        out.append(_Injection(target=target, marker=marker, snippet=snippet, position=position))
    return out


def _inject_snippet(file: Path, marker: str, snippet: str, position: str) -> None:
    """Insert `snippet` at a line containing `# FORGE:<marker>` or similar.

    The marker must appear *exactly once* in the file. The whole line containing
    the marker is preserved; `snippet` lands as a new line immediately after
    (or before) it. Indentation is copied from the marker line so the snippet
    slots into the existing block shape.
    """
    if not file.is_file():
        raise GeneratorError(f"Injection target not found: {file}")

    # Accept marker with or without the FORGE: prefix in the YAML.
    needle = marker if marker.startswith(MARKER_PREFIX) else f"{MARKER_PREFIX}{marker}"
    text = file.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    hits = [i for i, line in enumerate(lines) if needle in line]
    if not hits:
        raise GeneratorError(
            f"Marker '{needle}' not found in {file}. "
            "Add the marker to the base template or check the fragment's inject.yaml."
        )
    if len(hits) > 1:
        raise GeneratorError(
            f"Marker '{needle}' appears {len(hits)} times in {file}; must be unique."
        )

    idx = hits[0]
    marker_line = lines[idx]
    # Preserve the marker line's indentation for the injected snippet.
    indent = marker_line[: len(marker_line) - len(marker_line.lstrip(" \t"))]
    # Snippet may be multi-line; indent each line.
    snippet_lines = snippet.splitlines()
    indented = "".join(f"{indent}{line}\n" for line in snippet_lines)

    insert_at = idx + 1 if position == "after" else idx
    new_lines = lines[:insert_at] + [indented] + lines[insert_at:]
    file.write_text("".join(new_lines), encoding="utf-8")


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
