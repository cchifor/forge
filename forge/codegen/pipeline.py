"""Codegen pipeline — runs every schema-driven emitter during `forge new`.

Called once from ``generator.generate`` after all templates have been
rendered and before ``forge.toml`` is stamped. Each emit-site decides
which targets it writes based on the project's frontend + backend
choices.

Concretely:

    1. UI protocol schemas → per-frontend types file + per-Python-backend
       Pydantic models.
    2. Canvas component manifest → per-frontend ``canvas.manifest.json``.
    3. Shared enums → per-backend + per-frontend bindings placed next to
       the consuming code.

Epic O (1.1.0-alpha.1) — per-frontend paths + emitter flavours live in
:class:`forge.frontends.FrontendLayout`. Adding a frontend means
registering one ``FrontendLayout``; the pipeline picks it up without
editing.

All outputs are recorded in the provenance manifest with
``origin='base-template'`` since they're authoritative forge outputs,
not fragment overlays.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from forge.codegen import canvas_lint as canvas_lint_codegen
from forge.codegen import canvas_props as canvas_props_codegen
from forge.codegen import event_union as event_union_codegen
from forge.codegen.canvas_contract import build_manifest as build_canvas_manifest
from forge.codegen.canvas_contract import load_components as load_canvas_components
from forge.codegen.enums import emit_all as emit_enum_all
from forge.codegen.enums import load_enum_yaml
from forge.codegen.ui_protocol import (
    DEFAULT_SCHEMA_ROOT as UI_PROTOCOL_ROOT,
)
from forge.codegen.ui_protocol import (
    emit_dart,
    emit_pydantic,
    emit_typescript,
)
from forge.codegen.ui_protocol import (
    load_all as load_ui_schemas,
)
from forge.config import BackendLanguage, FrontendFramework
from forge.frontends import FrontendLayout, get_frontend_layout
from forge.logging import get_logger, log_event

if TYPE_CHECKING:
    from forge.capability_resolver import ResolvedPlan
    from forge.config import ProjectConfig
    from forge.sync.provenance import ProvenanceCollector


_TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "templates"
_ENUMS_ROOT = _TEMPLATES_ROOT / "_shared" / "domain" / "enums"

_LOGGER = get_logger(__name__)


def run_codegen(
    config: ProjectConfig,
    project_root: Path,
    collector: ProvenanceCollector | None = None,
    *,
    resolved: ResolvedPlan | None = None,
) -> None:
    """Run every schema-driven emitter and write outputs into the project tree.

    Safe to call unconditionally — if a target frontend/backend isn't
    present, the corresponding emitter quietly skips. Overwrites existing
    generated files (they're authoritative forge outputs — user edits to
    these are expected to be captured via `user` zones in the future).

    Initiative #2 sub-task 2: after the built-in passes run,
    :func:`_run_plugin_emitters` walks
    :data:`forge.plugins.LOADED_PLUGINS` and invokes every emitter
    registered via :meth:`forge.api.ForgeAPI.add_emitter`. ``resolved``
    is forwarded to plugin emitters as the third argument; it defaults
    to ``None`` because the in-tree generator path that calls
    ``run_codegen`` hasn't been plumbed with the resolved plan yet
    (deferred follow-up). Built-in passes do not consume ``resolved``.
    """
    _emit_ui_protocol(config, project_root, collector)
    _emit_canvas_manifests(config, project_root, collector)
    _emit_canvas_props_pydantic(config, project_root, collector)
    _emit_canvas_lint_packages(config, project_root, collector)
    _emit_event_union_pydantic(config, project_root, collector)
    _emit_shared_enums(config, project_root, collector)
    _run_plugin_emitters(config, project_root, resolved)


def _frontend_layout(config: ProjectConfig) -> FrontendLayout | None:
    """Return the active frontend's layout, or None if no frontend / unregistered."""
    if config.frontend is None or config.frontend.framework == FrontendFramework.NONE:
        return None
    return get_frontend_layout(config.frontend.framework)


def _emit_ui_protocol(
    config: ProjectConfig,
    project_root: Path,
    collector: ProvenanceCollector | None,
) -> None:
    """Regenerate UI-protocol types for the active frontend + Python backends."""
    schemas = load_ui_schemas(UI_PROTOCOL_ROOT)
    if not schemas:
        return

    layout = _frontend_layout(config)
    if layout is not None:
        target = project_root / config.frontend_slug / layout.ui_protocol_path
        if layout.ui_protocol_emitter == "typescript":
            body = emit_typescript(schemas)
        else:
            body = emit_dart(schemas)
        _write(target, body, collector)

    # Python backends always get Pydantic models, independent of frontend.
    for bc in config.backends:
        if bc.language is not BackendLanguage.PYTHON:
            continue
        target = project_root / "services" / bc.name / "src" / "app" / "domain" / "ui_protocol.py"
        _write(target, emit_pydantic(schemas), collector)


def _emit_canvas_manifests(
    config: ProjectConfig,
    project_root: Path,
    collector: ProvenanceCollector | None,
) -> None:
    """Write ``canvas.manifest.json`` into the frontend's declared location.

    The manifest is read at runtime (dev) to validate backend-emitted
    payloads match the component's declared props schema.
    """
    layout = _frontend_layout(config)
    if layout is None:
        return
    components = load_canvas_components()
    manifest_body = json.dumps(build_canvas_manifest(components), indent=2) + "\n"
    target = project_root / config.frontend_slug / layout.canvas_manifest_path
    _write(target, manifest_body, collector)


def _emit_canvas_props_pydantic(
    config: ProjectConfig,
    project_root: Path,
    collector: ProvenanceCollector | None,
) -> None:
    """Emit Pydantic models for every canvas-component prop schema.

    Generated file: ``services/<backend>/src/app/domain/canvas_props.py``
    for each Python backend. The TS / Dart variants live in the canvas
    packages themselves and are not per-project artifacts — they're
    regenerated from the forge repo via ``python -m
    forge.codegen.canvas_props``.
    """
    schemas = canvas_props_codegen.load_canvas_schemas()
    if not schemas:
        return
    body = canvas_props_codegen.emit_pydantic(schemas)
    for bc in config.backends:
        if bc.language is not BackendLanguage.PYTHON:
            continue
        target = project_root / "services" / bc.name / "src" / "app" / "domain" / "canvas_props.py"
        _write(target, body, collector)


def _emit_canvas_lint_packages(
    config: ProjectConfig,
    project_root: Path,
    collector: ProvenanceCollector | None,
) -> None:
    """Pipeline hook for the canvas lint codegen (Theme 1C).

    The lint implementations live in the canvas consumer packages
    (``packages/canvas-vue/src/lint.ts``,
    ``packages/canvas-svelte/src/lint.ts``,
    ``packages/forge-canvas-dart/lib/src/lint.dart``) — they are *not*
    per-project artifacts. Generated projects depend on the canvas
    packages from npm / pub.dev, so there is nothing to emit into
    ``project_root`` today.

    This hook is intentionally a no-op for ``forge new`` and exists for
    symmetry with the other ``_emit_*`` dispatchers in this module —
    future work might emit per-project lint shims (e.g. a project-local
    component whose props schema is declared in the project, not in
    forge) and this is the seam where that emission would land.

    To regenerate the repo-side ``packages/`` lint files, run
    ``python -m forge.codegen.canvas_lint`` (or call
    :func:`forge.codegen.canvas_lint.regenerate_packages` directly).
    """
    _ = canvas_lint_codegen.SCHEMA_VERSION
    return


def _emit_event_union_pydantic(
    config: ProjectConfig,
    project_root: Path,
    collector: ProvenanceCollector | None,
) -> None:
    """Emit the discriminated-union Pydantic module for every Python backend.

    Generated file: ``services/<backend>/src/app/domain/canvas_events.py``.
    Imports the variant payload classes from the sibling
    ``ui_protocol.py`` (the Theme 1B output).

    Also emits a per-frontend ``events.gen.ts`` / ``events.gen.dart``
    when the frontend's :attr:`FrontendLayout.event_union_path` is set.
    The repo-side canvas packages (``packages/canvas-*``) carry their
    own copy regenerated by ``python -m forge.codegen.event_union``.
    """
    schemas = event_union_codegen.load_event_schemas()
    if not schemas:
        return
    body = event_union_codegen.emit_pydantic(schemas)
    for bc in config.backends:
        if bc.language is not BackendLanguage.PYTHON:
            continue
        target = project_root / "services" / bc.name / "src" / "app" / "domain" / "canvas_events.py"
        _write(target, body, collector)

    layout = _frontend_layout(config)
    if layout is None or not layout.event_union_path:
        return
    target = project_root / config.frontend_slug / layout.event_union_path
    if layout.ui_protocol_emitter == "typescript":
        fe_body = event_union_codegen.emit_typescript(schemas)
    else:
        fe_body = event_union_codegen.emit_dart(schemas)
    _write(target, fe_body, collector)


def _emit_shared_enums(
    config: ProjectConfig,
    project_root: Path,
    collector: ProvenanceCollector | None,
) -> None:
    """Emit each shared enum into the right place for each backend/frontend.

    Shared enums (``_shared/domain/enums/*.yaml``) are authoritative —
    the generator owns their emitted form; users should not edit the
    generated files directly.
    """
    if not _ENUMS_ROOT.is_dir():
        return

    layout = _frontend_layout(config)

    for enum_file in sorted(_ENUMS_ROOT.glob("*.yaml")):
        spec = load_enum_yaml(enum_file)
        targets = emit_enum_all(spec)

        # Python / Node / Rust backends — paths are conventional, not
        # registered. Adding a plugin backend needs the same
        # {"services/<name>/..."} shape or a dedicated backend-layout
        # registry (deferred; no plugin backend ships today).
        for bc in config.backends:
            if bc.language is BackendLanguage.PYTHON:
                path = (
                    project_root
                    / "services"
                    / bc.name
                    / "src"
                    / "app"
                    / "domain"
                    / "enums"
                    / f"{enum_file.stem}.py"
                )
                _write(path, targets["python"], collector)
            elif bc.language is BackendLanguage.NODE:
                path = (
                    project_root
                    / "services"
                    / bc.name
                    / "src"
                    / "schemas"
                    / "enums"
                    / f"{enum_file.stem}.ts"
                )
                _write(path, targets["zod"], collector)
            elif bc.language is BackendLanguage.RUST:
                path = (
                    project_root
                    / "services"
                    / bc.name
                    / "src"
                    / "models"
                    / "enums"
                    / f"{enum_file.stem}.rs"
                )
                _write(path, targets["rust"], collector)

        # Frontend — one enum emission per registered layout.
        if layout is None:
            continue
        ext = ".ts" if layout.shared_enums_emitter == "typescript" else ".dart"
        emitter_key = "typescript" if layout.shared_enums_emitter == "typescript" else "dart"
        path = (
            project_root / config.frontend_slug / layout.shared_enums_dir / f"{enum_file.stem}{ext}"
        )
        _write(path, targets[emitter_key], collector)


def _write(
    target: Path,
    content: str,
    collector: ProvenanceCollector | None,
) -> None:
    """Write ``content`` to ``target`` and record base-template provenance."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    if collector is not None:
        # Codegen outputs are derived from authoritative schemas under
        # ``forge/templates/_shared/`` (UI protocol JSON Schemas, canvas
        # component definitions, shared enum YAMLs) — they aren't a
        # Copier template and have no version field today. Tag them with
        # a synthetic name so harvest can distinguish codegen outputs
        # from backend/frontend template outputs; leave template_version
        # None until the underlying schemas grow semver.
        # TODO: thread schema-set version once
        # ``forge/templates/_shared/`` adopts a manifest with a version.
        collector.record(
            target,
            origin="base-template",
            template_name="_codegen",
            template_version=None,
        )


# ---------------------------------------------------------------------------
# Plugin emitter walk (Initiative #2 sub-task 2)
# ---------------------------------------------------------------------------


def _run_plugin_emitters(
    config: ProjectConfig,
    project_root: Path,
    resolved: ResolvedPlan | None,
) -> None:
    """Walk LOADED_PLUGINS and invoke every plugin-registered emitter.

    Mirrors the harvester's
    :func:`forge.sync.project_to_forge.harvester._orchestrator._collect_global_plugin_extractor_overrides`
    pattern: each plugin's ``emitter_registrations`` tuple is iterated
    in plugin-load order, with last-loaded winning on target collision.

    Emitter exceptions are caught and logged — a broken plugin emitter
    must not abort codegen for the remaining plugins. The caller
    (``forge.generator._apply_project_scope``) already wraps
    ``run_codegen`` in a try/except that downgrades any escape to a
    warning, but per-plugin isolation here means one bad plugin
    doesn't shadow every plugin that follows.
    """
    from forge.plugins import LOADED_PLUGINS  # noqa: PLC0415

    winners: dict[str, str] = {}
    for plugin in LOADED_PLUGINS:
        for registration in plugin.emitter_registrations:
            prior_winner = winners.get(registration.target)
            if prior_winner is not None and prior_winner != plugin.name:
                _warn_emitter_target_collision(
                    target=registration.target,
                    loser=prior_winner,
                    winner=plugin.name,
                )
            winners[registration.target] = plugin.name
            try:
                registration.emitter(project_root, config, resolved)
            except Exception as exc:  # noqa: BLE001 — isolate per-plugin failure
                log_event(
                    _LOGGER,
                    "plugin.emitter.failed",
                    level=logging.WARNING,
                    message=(
                        f"plugin {plugin.name!r} emitter for target "
                        f"{registration.target!r} raised "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    plugin=plugin.name,
                    target=registration.target,
                    error_type=type(exc).__name__,
                )


def _warn_emitter_target_collision(
    *, target: str, loser: str, winner: str
) -> None:
    """Emit a structured warning when two plugins claim the same target.

    Collision warnings are NOT deduplicated: each codegen invocation
    that exhibits the collision deserves the signal because resolution
    depends on plugin load order — operators should see it on every
    ``forge new`` until the conflict is resolved.

    Mirrors
    :func:`forge.sync.project_to_forge.harvester._orchestrator._warn_global_override_collision`
    so the two collision-warning surfaces share the same shape.
    """
    log_event(
        _LOGGER,
        "plugin.emitter.target_collision",
        level=logging.WARNING,
        message=(
            f"plugin {winner!r} overrode the codegen emitter for target "
            f"{target!r} previously registered by plugin {loser!r}; "
            "last-loaded wins by default"
        ),
        target=target,
        winner=winner,
        loser=loser,
    )
