"""Applier for a fragment's language-specific dependency adds.

Merges fragment-declared deps into the target backend's package
manifest (``pyproject.toml`` / ``package.json`` / ``Cargo.toml``) in a
way that preserves user-authored entries. Raises
:class:`FragmentError` when the manifest is missing, malformed, or the
fragment's spec string doesn't parse.

Epic 1b (P1.1) lifts the bodies out of
``forge.feature_injector._add_dependencies`` into this module; the
legacy function names are re-exported there for one minor as
backward-compat shims for tests + plugins that imported them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomlkit

from forge.config import BackendLanguage
from forge.errors import (
    FRAGMENT_DEP_SPEC_INVALID,
    FRAGMENT_DEPS_FILE_MISSING,
    FRAGMENT_DEPS_SECTION_MISSING,
    FragmentError,
)

if TYPE_CHECKING:
    from forge.appliers.plan import FragmentPlan
    from forge.fragment_context import FragmentContext


class FragmentDepsApplier:
    """Adds fragment dependencies to the backend's package manifest."""

    def apply(self, ctx: FragmentContext, plan: FragmentPlan) -> None:
        if not plan.dependencies:
            return
        _add_dependencies(ctx.backend_config.language, ctx.backend_dir, plan.dependencies)


def _add_dependencies(lang: BackendLanguage, backend_dir: Path, deps: tuple[str, ...]) -> None:
    """Dispatch ``deps`` into the right per-language manifest editor."""
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
