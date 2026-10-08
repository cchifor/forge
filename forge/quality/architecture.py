"""Re-rendered integrity checks and dependency boundary validation."""

from __future__ import annotations

import ast
import re
import shutil
from pathlib import Path

from forge.quality.model import (
    IGNORED,
    SOURCE_SUFFIXES,
    digest,
    ownership,
    project_path,
    read_recipe,
)
from forge.sync.manifest import read_forge_toml


def imports(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        tree = ast.parse(text, filename=str(path))
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                found.append("." * node.level + (node.module or ""))
            elif (
                (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "__import__"
                )
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                found.append(str(node.args[0].value))
        return found
    if path.suffix == ".rs":
        return re.findall(r"\b(?:use|mod)\s+([\w:]+)", text)
    # Static and literal dynamic ES imports, require, Dart imports/exports.
    return re.findall(
        r"(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*|\bexport\s*)['\"]([^'\"]+)['\"]", text
    )


def boundary_violations(root: Path, records: dict) -> list[str]:
    problems: list[str] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if (
            not path.is_file()
            or path.suffix not in SOURCE_SUFFIXES
            or set(path.relative_to(root).parts) & IGNORED
        ):
            continue
        project_path(root, rel)
        if "tests" in path.parts or "test" in path.parts:
            continue
        policy = records.get(rel, {}).get("ownership", "user")
        try:
            dependencies = imports(path)
        except (SyntaxError, UnicodeError) as exc:
            problems.append(f"{rel}: cannot inspect source: {exc}")
            continue
        for dependency in dependencies:
            segments = [s for s in re.split(r"[./:]", dependency) if s]
            if policy == "generated" and "custom" in segments:
                problems.append(f"{rel}: generated code imports application extension {dependency}")
            if (
                policy != "generated"
                and ("_template" in segments or any(s.startswith("_") for s in segments))
                and (
                    "generated" in segments
                    or "_template" in segments
                    or "forge_core" in segments
                    or "platform_auth" in segments
                )
            ):
                problems.append(
                    f"{rel}: import private generated implementation {dependency}; use its public port"
                )
        # Reject assignment through an imported generated module (monkey patch).
        if policy != "generated" and path.suffix == ".py":
            tree = ast.parse(path.read_text(encoding="utf-8"))
            aliases = {
                a.asname or a.name.split(".")[0]
                for n in ast.walk(tree)
                if isinstance(n, ast.Import)
                for a in n.names
                if any(x in a.name.split(".") for x in ("forge_core", "platform_auth", "generated"))
            }
            aliases.update(
                a.asname or a.name
                for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom)
                and any(
                    x in (n.module or "").split(".")
                    for x in ("forge_core", "platform_auth", "generated")
                )
                for a in n.names
            )
            for node in ast.walk(tree):
                targets = (
                    node.targets
                    if isinstance(node, ast.Assign)
                    else [node.target]
                    if isinstance(node, (ast.AnnAssign, ast.AugAssign))
                    else []
                )
                for target in targets:
                    if not isinstance(target, (ast.Attribute, ast.Subscript)):
                        continue
                    while isinstance(target, (ast.Attribute, ast.Subscript)):
                        target = target.value
                    if isinstance(target, ast.Name) and target.id in aliases:
                        problems.append(
                            f"{rel}:{getattr(node, 'lineno', 0)}: cannot replace generated module members"
                        )
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in {"setattr", "delattr"}
                    and node.args
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id in aliases
                ):
                    problems.append(
                        f"{rel}:{node.lineno}: cannot patch generated members with {node.func.id}"
                    )
        if policy != "generated" and path.suffix in {
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".vue",
            ".svelte",
        }:
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"\bimport\s+(.+?)\s+from\s*['\"]([^'\"]+)['\"]", text):
                clause, dependency = match.groups()
                if not any(
                    part in re.split(r"[./:@-]", dependency)
                    for part in ("generated", "core", "_template", "platform", "shared")
                ):
                    continue
                names = [
                    part.strip().split()[-1]
                    for part in clause.replace("{", "").replace("}", "").split(",")
                    if part.strip()
                ]
                for name in names:
                    if re.search(r"(?m)^\s*" + re.escape(name) + r"(?:\.\w+)+\s*=(?!=)", text):
                        problems.append(f"{rel}: cannot replace generated member on {name}")
    return problems


def verify_architecture(root: Path) -> dict:
    """Compare against trusted regeneration, not editable local provenance."""
    from forge.generator import generate

    config = read_recipe(root)
    candidate = generate(config, quiet=True, dry_run=True)
    try:
        expected = read_forge_toml(candidate / "forge.toml").provenance
        local = read_forge_toml(root / "forge.toml").provenance
        problems: list[str] = []
        protected = 0
        for rel, record in expected.items():
            record["ownership"] = ownership(rel, record["origin"], record.get("template_name"))
            if record["ownership"] != "generated":
                continue
            protected += 1
            path = project_path(root, rel)
            if not path.is_file() or digest(path) != digest(candidate / rel):
                problems.append(f"{rel}: protected generated output differs from regeneration")
            if local.get(rel, {}).get("ownership") != "generated":
                problems.append(f"{rel}: generated ownership missing or changed")
        for rel, record in local.items():
            if record.get("ownership") == "generated" and rel not in expected:
                problems.append(f"{rel}: obsolete or unrecognized generated output")
        for path in root.rglob("*"):
            rel = path.relative_to(root).as_posix()
            if (
                path.is_file()
                and not set(path.relative_to(root).parts) & IGNORED
                and rel not in expected
                and ownership(rel) == "generated"
            ):
                problems.append(f"{rel}: unregistered source in a generated namespace")
        problems.extend(boundary_violations(root, expected))
        return {"passed": not problems, "protected_files": protected, "violations": problems}
    finally:
        shutil.rmtree(candidate)
