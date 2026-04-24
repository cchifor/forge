"""`forge --update` — re-apply options to an existing forge-generated project.

Reads the ``[forge.options]`` stamp from ``forge.toml``, runs the current
resolver against it, re-applies every fragment to each discovered
backend, then re-stamps ``forge.toml`` with the current forge version
and the fully-defaulted option map. Injections are idempotent (B2.3
sentinels), so running this repeatedly is a no-op when nothing changed
and a clean in-place update when a fragment snippet was modified or a
new Option was added.

Provenance classification (1.0.0a1+):
  Before re-applying, ``classify_project_state`` compares each recorded
  file's SHA to the on-disk content and returns a per-path state:
    * ``unchanged`` — safe to re-emit
    * ``user-modified`` — preserve; skip fragment files, warn on injection targets
    * ``missing`` — user deleted; re-emit

The classification is exposed in the summary dict and used to guide
``skip_existing_files`` decisions. Full three-way merge lands in Phase 2.2.

Out of scope (still):
  - Template-level Copier updates (base template changes). Users who want
    those can ``cd <backend>/`` and run ``copier update`` directly —
    ``.copier-answers.yml`` is the input.
  - Deleting files from Options that were turned off. Needs the provenance
    manifest follow-up — partial in this alpha; full in 1.0.0a3.
"""

from __future__ import annotations

import logging
from importlib import metadata
from pathlib import Path
from typing import Any

from forge.capability_resolver import ResolvedPlan, resolve
from forge.config import BACKEND_REGISTRY, BackendConfig, BackendLanguage, ProjectConfig
from forge.errors import (
    PROVENANCE_MANIFEST_MISSING,
    ForgeError,
    OptionsError,
    ProvenanceError,
)
from forge.feature_injector import apply_features, apply_project_features
from forge.forge_toml import ForgeTomlData, read_forge_toml, write_forge_toml
from forge.provenance import FileState, ProvenanceCollector, ProvenanceRecord, classify
from forge.sentinel_audit import audit_targets, raise_if_corrupt
from forge.uninstaller import (
    UninstallOutcome,
    disabled_fragments,
    uninstall_fragment,
)
from forge.updater_lock import acquire_lock

logger = logging.getLogger(__name__)


def update_project(
    project_root: Path,
    quiet: bool = False,
    *,
    no_lock: bool = False,
) -> dict[str, object]:
    """Re-apply option-driven fragments to the project at ``project_root``.

    Returns a summary dict with ``backends``, ``fragments_applied``, and
    ``forge_version_before`` / ``forge_version_after`` keys. Raises
    :class:`ProvenanceError` if ``project_root`` isn't a forge-generated
    project (no ``forge.toml``) or if the registry no longer recognises
    a recorded option path.
    """
    manifest = project_root / "forge.toml"
    if not manifest.is_file():
        raise ProvenanceError(
            f"No forge.toml at {project_root}. Is this a forge-generated project?",
            code=PROVENANCE_MANIFEST_MISSING,
            context={"project_root": str(project_root)},
        )

    # Epic H (1.1.0-alpha.1) — serialise concurrent updates via .forge/lock.
    with acquire_lock(project_root, no_lock=no_lock):
        return _update_locked(project_root, manifest, quiet=quiet)


def _update_locked(
    project_root: Path,
    manifest: Path,
    *,
    quiet: bool,
) -> dict[str, object]:
    """Main update body, called with the .forge/lock held."""
    data = read_forge_toml(manifest)
    try:
        current_version = metadata.version("forge")
    except metadata.PackageNotFoundError:
        current_version = "0.0.0+unknown"

    backends = _infer_backends(project_root)
    if not backends:
        raise ProvenanceError(
            f"No services/<backend>/ directories found under {project_root}. Nothing to update.",
            context={"project_root": str(project_root)},
        )

    config = ProjectConfig(
        project_name=data.project_name or project_root.name,
        backends=list(backends),
        options=dict(data.options),
    )

    try:
        plan = resolve(config)
    except ForgeError as e:
        # Preserve the underlying error's code/context when re-raising so the
        # CLI envelope stays informative about which option path was at fault.
        raise OptionsError(
            f"Cannot resolve option plan from forge.toml: {e.message}. "
            "An option path or fragment may have been removed since this project "
            "was generated.",
            code=e.code,
            hint=e.hint,
            context={**e.context, "project_root": str(project_root)},
        ) from e

    # Classify every provenance-tracked file BEFORE re-applying. The
    # classification feeds the summary (user visibility) and warns about
    # user-modified files that are about to be left alone by the
    # skip_existing_files=True apply path.
    classification = classify_project_state(project_root, data.provenance)
    user_modified = [p for p, s in classification.items() if s == "user-modified"]
    if user_modified and not quiet:
        print(f"  [update] {len(user_modified)} file(s) modified since last generate:")
        for p in user_modified[:10]:
            print(f"    * {p}")
        if len(user_modified) > 10:
            print(f"    ... and {len(user_modified) - 10} more")
        print(
            "  [update] skip_existing_files=True — these files are preserved. "
            "Three-zone merge lands in 1.0.0a3."
        )

    # Fresh collector for the post-update provenance re-stamp. Carries over
    # any prior records we can't re-derive (user-labeled files).
    collector = ProvenanceCollector(project_root=project_root)
    for rel, entry in data.provenance.items():
        if entry.get("origin") == "user":
            collector.records[rel] = ProvenanceRecord(
                origin="user",
                sha256=str(entry.get("sha256", "")),
            )

    # Epic H — sentinel audit before re-injection. If a hand-edit broke
    # a BEGIN/END pair, raise here with the file+tag+line rather than
    # silently double-injecting.
    injection_targets = _collect_injection_targets(project_root, plan, config.backends)
    issues = audit_targets(injection_targets)
    if issues:
        if not quiet:
            print(
                f"  [update] sentinel audit found {len(issues)} structural issue(s) — aborting"
            )
        raise_if_corrupt(issues)

    # Epic F — provenance-driven uninstall. Any fragment present in the
    # previous run's provenance but missing from the current plan gets
    # its files deleted (or preserved when user-modified). Opt out by
    # setting `forge.update.no_uninstall = true` in forge.toml — used
    # by the 1.1.x compat layer + projects that manage teardown
    # manually.
    uninstall_outcomes: list[UninstallOutcome] = []
    if not _no_uninstall_flag(manifest):
        current_plan_fragments = {rf.fragment.name for rf in plan.ordered}
        disabled = disabled_fragments(data.provenance, current_plan_fragments)
        if disabled and not quiet:
            names = ", ".join(sorted(disabled))
            print(f"  [update] uninstalling {len(disabled)} disabled fragment(s): {names}")
        for name in sorted(disabled):
            outcome = uninstall_fragment(
                project_root,
                name,
                data.provenance,
                collector,
                removed_blocks_in_files=_disabled_fragment_blocks(
                    project_root, name, data
                ),
            )
            uninstall_outcomes.append(outcome)
            if not quiet:
                if outcome.deleted_files:
                    print(
                        f"    [{name}] deleted {len(outcome.deleted_files)} file(s)"
                    )
                if outcome.preserved_files:
                    print(
                        f"    [{name}] preserved {len(outcome.preserved_files)} user-modified file(s)"
                    )
                if outcome.removed_blocks:
                    print(
                        f"    [{name}] scrubbed {len(outcome.removed_blocks)} injected block(s)"
                    )
                if outcome.conflicted_blocks:
                    print(
                        f"    [{name}] {len(outcome.conflicted_blocks)} block(s) "
                        "needed manual review — see .forge-merge sidecars"
                    )

    fragments_applied: list[str] = []
    for bc in config.backends:
        backend_dir = project_root / "services" / bc.name
        if not backend_dir.is_dir():
            continue
        if not quiet:
            print(f"  [update] re-applying fragments to {bc.name} ({bc.language.value}) ...")
        apply_features(
            bc,
            backend_dir,
            plan.ordered,
            quiet=quiet,
            skip_existing_files=True,
            collector=collector,
            option_values=plan.option_values,
            project_root=project_root,
        )

    if not quiet:
        print("  [update] re-applying project-scope fragments ...")
    apply_project_features(
        project_root,
        plan.ordered,
        quiet=quiet,
        skip_existing_files=True,
        collector=collector,
        option_values=plan.option_values,
    )

    for rf in plan.ordered:
        if rf.fragment.name not in fragments_applied:
            fragments_applied.append(rf.fragment.name)

    _restamp_forge_toml(
        manifest=manifest,
        project_name=data.project_name or project_root.name,
        backends=tuple(config.backends),
        option_values=plan.option_values,
        current_version=current_version,
        provenance=collector.as_dict(),
        merge_blocks=collector.merge_blocks_as_dict(),
    )

    return {
        "backends": [bc.name for bc in config.backends],
        "fragments_applied": fragments_applied,
        "forge_version_before": data.version,
        "forge_version_after": current_version,
        "classification": {p: s for p, s in classification.items()},
        "user_modified_count": len(user_modified),
        "uninstalled": [o.as_dict() for o in uninstall_outcomes],
    }


def _collect_injection_targets(
    project_root: Path,
    plan: ResolvedPlan,
    backends: list[BackendConfig],
) -> list[Path]:
    """Return every file path the plan's injections would touch.

    Used by Epic H's sentinel audit to scan for corrupted BEGIN/END
    pairs before injection runs. The set is the union of inject.yaml
    targets across every resolved fragment × every matching backend.
    Duplicates are collapsed — one file audited once is enough.
    """
    from forge.appliers.plan import FragmentPlan  # noqa: PLC0415

    seen: set[Path] = set()
    for rf in plan.ordered:
        for bc in backends:
            if bc.language not in rf.target_backends:
                continue
            impl = rf.fragment.implementations.get(bc.language)
            if impl is None or impl.scope != "backend":
                continue
            backend_dir = project_root / "services" / bc.name
            try:
                fp = FragmentPlan.from_impl(
                    impl,
                    rf.fragment.name,
                    options={},
                    middlewares=rf.fragment.middlewares,
                    backend=bc.language,
                )
            except Exception:  # noqa: BLE001
                # If the plan can't even be built, the audit can't help —
                # the main apply pass will raise with the same error.
                continue
            for inj in fp.injections:
                seen.add(backend_dir / inj.target)
    return sorted(seen)


def _no_uninstall_flag(manifest: Path) -> bool:
    """Read ``[forge.update].no_uninstall`` from ``forge.toml``.

    Returns ``True`` when the project explicitly opts out of Epic F's
    provenance-driven uninstall. Falls back to ``False`` when the key
    is absent or the manifest is unreadable.
    """
    try:
        import tomlkit  # noqa: PLC0415

        doc = tomlkit.parse(manifest.read_text(encoding="utf-8"))
        update_tbl = doc.get("forge", {}).get("update") or {}
        return bool(update_tbl.get("no_uninstall", False))
    except Exception:  # noqa: BLE001
        return False


def _disabled_fragment_blocks(
    project_root: Path,
    fragment_name: str,
    data: ForgeTomlData,
) -> list[tuple[str, str, str]]:
    """Produce the ``(rel_path, feature_key, marker)`` list for a disabled fragment's injections.

    We can't look the fragment up in the live registry (it's been
    removed, which is why we're uninstalling it). Instead, we derive
    the injection targets by walking ``[forge.merge_blocks]`` for
    entries keyed by this fragment's feature key. Epic H records every
    merge-zone injection here; ordinary (``generated``-zone) injections
    don't record their baseline here, so they won't be scrubbed from
    their target files — that trade-off is acceptable for Epic F phase
    1 because ``generated``-zone injections are owned by the fragment,
    not merged, so the text between BEGIN/END is unambiguously safe
    to remove on re-apply (the next ``--update`` that runs the full
    applier pipeline handles it naturally).
    """
    from forge.merge import MergeBlockCollector  # noqa: PLC0415

    out: list[tuple[str, str, str]] = []
    for key in data.merge_blocks:
        parsed = MergeBlockCollector.parse_key(key)
        if parsed is None:
            continue
        rel_path, feature_key, marker = parsed
        if feature_key == fragment_name:
            out.append((rel_path, feature_key, marker))
    return out


def classify_project_state(
    project_root: Path, provenance_tbl: dict[str, dict[str, str]]
) -> dict[str, FileState]:
    """Classify every recorded file as unchanged / user-modified / missing.

    Files not in the provenance table are invisible to this pass — the
    updater assumes the user created them on purpose. When the provenance
    table is empty (old pre-1.0 project), returns an empty classification
    and the updater falls back to its legacy skip_existing behavior.
    """
    out: dict[str, FileState] = {}
    for rel, entry in provenance_tbl.items():
        sha = str(entry.get("sha256", ""))
        if not sha:
            continue
        path = project_root / rel
        rec = ProvenanceRecord(origin="base-template", sha256=sha)
        out[rel] = classify(path, rec)
    return out


def _infer_backends(project_root: Path) -> list[BackendConfig]:
    """Discover backends from on-disk layout.

    Each ``services/<name>/`` is a backend. Language is inferred from the
    language-specific marker file present: ``pyproject.toml`` → python,
    ``package.json`` → node, ``Cargo.toml`` → rust.
    """
    services = project_root / "services"
    if not services.is_dir():
        return []

    markers: dict[str, BackendLanguage] = {
        "pyproject.toml": BackendLanguage.PYTHON,
        "package.json": BackendLanguage.NODE,
        "Cargo.toml": BackendLanguage.RUST,
    }

    out: list[BackendConfig] = []
    for backend_dir in sorted(services.iterdir()):
        if not backend_dir.is_dir():
            continue
        for marker, lang in markers.items():
            if (backend_dir / marker).is_file():
                out.append(
                    BackendConfig(
                        name=backend_dir.name,
                        project_name=project_root.name,
                        language=lang,
                    )
                )
                break
    return out


def _restamp_forge_toml(
    manifest: Path,
    *,
    project_name: str,
    backends: tuple[BackendConfig, ...],
    option_values: dict[str, Any],
    current_version: str,
    provenance: dict[str, dict[str, str]] | None = None,
    merge_blocks: dict[str, dict[str, str]] | None = None,
) -> None:
    """Write forge.toml with the current version + options + provenance + merge blocks."""
    templates: dict[str, str] = {}
    for lang in sorted({bc.language for bc in backends}, key=lambda L: L.value):
        templates[lang.value] = BACKEND_REGISTRY[lang].template_dir

    write_forge_toml(
        manifest,
        version=current_version,
        project_name=project_name,
        templates=templates,
        options=dict(option_values),
        provenance=provenance,
        merge_blocks=merge_blocks,
    )
