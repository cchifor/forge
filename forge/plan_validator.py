"""Pre-generation plan validation (P1.3).

Checks each resolved fragment can be applied before Copier renders the
backend templates. Any failures raised here surface in under 100ms —
versus the 5+ seconds the full generate() pipeline takes before the
feature injector catches the same issue. The trade-off is that we
only see *static* problems (missing fragment directories, malformed
``inject.yaml``, duplicate env keys, overlapping file copies); anchor
existence is still verified at application time when markers live in
rendered templates.

The validator is additive: it raises the first batch of errors as a
single :class:`PlanValidationError` so authors see every problem at
once rather than playing whack-a-mole across generate runs.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

from forge.capability_resolver import ResolvedFragment, ResolvedPlan
from forge.config import BackendLanguage
from forge.errors import ForgeError
from forge.feature_injector import _resolve_fragment_dir


class PlanValidationError(ForgeError):
    """Raised when the resolved plan would fail to apply as-is."""


@dataclass
class _Issue:
    fragment: str
    backend: str
    path: str
    detail: str

    def render(self) -> str:
        return f"  - [{self.fragment} / {self.backend}] {self.path}: {self.detail}"


def validate_plan(plan: ResolvedPlan) -> None:
    """Validate ``plan`` statically. Raises :class:`PlanValidationError`
    on the first non-empty batch of issues, aggregating every problem
    found across the plan.
    """
    issues: list[_Issue] = []

    seen_files: dict[str, str] = {}  # target path → fragment that owns it

    for resolved in plan.ordered:
        for backend in resolved.target_backends:
            impl = resolved.fragment.implementations.get(backend)
            if impl is None:
                continue
            frag_dir = _resolve_fragment_dir(impl.fragment_dir)
            issues.extend(_check_fragment_root(resolved, backend, frag_dir))
            issues.extend(_check_inject_yaml(resolved, backend, frag_dir))
            issues.extend(_check_env_yaml(resolved, backend, frag_dir))
            issues.extend(_check_file_overlap(resolved, backend, frag_dir, seen_files))

    if issues:
        rendered = "\n".join(i.render() for i in issues)
        raise PlanValidationError(
            "Plan validation found the following issues:\n" + rendered,
            code="PLAN_VALIDATION_FAILED",
            context={
                "issue_count": len(issues),
                "issues": [
                    {
                        "fragment": i.fragment,
                        "backend": i.backend,
                        "path": i.path,
                        "detail": i.detail,
                    }
                    for i in issues
                ],
            },
        )


def _check_fragment_root(
    resolved: ResolvedFragment, backend: BackendLanguage, frag_dir: Path
) -> Iterable[_Issue]:
    if not frag_dir.is_dir():
        yield _Issue(
            fragment=resolved.fragment.name,
            backend=backend.value,
            path=str(frag_dir),
            detail="fragment directory does not exist",
        )


def _check_inject_yaml(
    resolved: ResolvedFragment, backend: BackendLanguage, frag_dir: Path
) -> Iterable[_Issue]:
    inject_yaml = frag_dir / "inject.yaml"
    if not inject_yaml.is_file():
        return
    try:
        parsed = yaml.safe_load(inject_yaml.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        yield _Issue(
            fragment=resolved.fragment.name,
            backend=backend.value,
            path=str(inject_yaml),
            detail=f"inject.yaml failed to parse: {exc}",
        )
        return
    if parsed is None:
        return
    if not isinstance(parsed, list):
        yield _Issue(
            fragment=resolved.fragment.name,
            backend=backend.value,
            path=str(inject_yaml),
            detail=f"inject.yaml top-level must be a list, got {type(parsed).__name__}",
        )
        return
    for idx, raw_entry in enumerate(parsed):
        if not isinstance(raw_entry, dict):
            yield _Issue(
                fragment=resolved.fragment.name,
                backend=backend.value,
                path=f"{inject_yaml}[{idx}]",
                detail=f"entry must be a mapping, got {type(raw_entry).__name__}",
            )
            continue
        # Cast explicitly so ty doesn't narrow the key type to ``Never``
        # via the literal-string ``in`` checks below (``dict`` is invariant).
        entry = cast(dict[str, Any], raw_entry)
        for required in ("target", "marker", "snippet"):
            if required not in entry and "anchor" not in entry:
                # `anchor` is an alias for `marker` in some fragments.
                if required == "marker" and "anchor" in entry:
                    continue
                yield _Issue(
                    fragment=resolved.fragment.name,
                    backend=backend.value,
                    path=f"{inject_yaml}[{idx}]",
                    detail=f"missing required key '{required}'",
                )
        position = entry.get("position")
        if position is not None and position not in ("before", "after"):
            yield _Issue(
                fragment=resolved.fragment.name,
                backend=backend.value,
                path=f"{inject_yaml}[{idx}]",
                detail=f"position must be 'before' or 'after', got {position!r}",
            )


def _check_env_yaml(
    resolved: ResolvedFragment, backend: BackendLanguage, frag_dir: Path
) -> Iterable[_Issue]:
    env_yaml = frag_dir / "env.yaml"
    if not env_yaml.is_file():
        return
    try:
        parsed = yaml.safe_load(env_yaml.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        yield _Issue(
            fragment=resolved.fragment.name,
            backend=backend.value,
            path=str(env_yaml),
            detail=f"env.yaml failed to parse: {exc}",
        )
        return
    if parsed is None:
        return
    if not isinstance(parsed, dict):
        yield _Issue(
            fragment=resolved.fragment.name,
            backend=backend.value,
            path=str(env_yaml),
            detail=f"env.yaml top-level must be a mapping, got {type(parsed).__name__}",
        )
        return
    seen: set[str] = set()
    for key in parsed:
        if not isinstance(key, str):
            yield _Issue(
                fragment=resolved.fragment.name,
                backend=backend.value,
                path=str(env_yaml),
                detail=f"env key {key!r} is not a string",
            )
            continue
        if key in seen:
            yield _Issue(
                fragment=resolved.fragment.name,
                backend=backend.value,
                path=str(env_yaml),
                detail=f"duplicate env key {key!r}",
            )
        seen.add(key)


def _check_file_overlap(
    resolved: ResolvedFragment,
    backend: BackendLanguage,
    frag_dir: Path,
    seen_files: dict[str, str],
) -> Iterable[_Issue]:
    files_dir = frag_dir / "files"
    if not files_dir.is_dir():
        return
    for path in files_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(files_dir).as_posix()
        key = f"{backend.value}:{rel}"
        owner = seen_files.get(key)
        if owner is not None and owner != resolved.fragment.name:
            yield _Issue(
                fragment=resolved.fragment.name,
                backend=backend.value,
                path=rel,
                detail=(
                    f"file overlaps with fragment {owner!r} "
                    "(both fragments would write the same target)"
                ),
            )
        else:
            seen_files[key] = resolved.fragment.name
