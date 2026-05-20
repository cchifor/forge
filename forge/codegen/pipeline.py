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

import hashlib
import json
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

if TYPE_CHECKING:
    from forge.config import ProjectConfig
    from forge.sync.provenance import ProvenanceCollector


_TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "templates"
_ENUMS_ROOT = _TEMPLATES_ROOT / "_shared" / "domain" / "enums"


def run_codegen(
    config: ProjectConfig,
    project_root: Path,
    collector: ProvenanceCollector | None = None,
) -> None:
    """Run every schema-driven emitter and write outputs into the project tree.

    Safe to call unconditionally — if a target frontend/backend isn't
    present, the corresponding emitter quietly skips. Overwrites existing
    generated files (they're authoritative forge outputs — user edits to
    these are expected to be captured via `user` zones in the future).
    """
    _emit_ui_protocol(config, project_root, collector)
    _emit_canvas_manifests(config, project_root, collector)
    _emit_canvas_props_pydantic(config, project_root, collector)
    _emit_canvas_lint_packages(config, project_root, collector)
    _emit_event_union_pydantic(config, project_root, collector)
    _emit_shared_enums(config, project_root, collector)


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
    """Write ``content`` to ``target`` and record base-template provenance.

    Initiative #6 (caching) — content-skip: when ``target`` already
    exists and the sha256 of its decoded UTF-8 text matches the sha256
    of ``content``, the write is skipped. The compare is done at the
    decoded-text level (not raw bytes) because :meth:`Path.write_text`
    with the default ``newline=None`` translates ``\\n`` to the
    platform line separator on Windows, so a raw-bytes compare on a
    cross-platform manifest would produce a false miss on every
    Windows run even when the next write would emit identical on-disk
    bytes. The skip therefore fires whenever the next ``write_text``
    would produce a logically-identical file — line-ending churn
    doesn't trigger rewrites, but every content drift does.

    Result: mtime is preserved, fsync churn drops, and IDEs / file
    watchers don't fire spurious "file changed" events for codegen
    outputs that didn't actually change. Provenance recording still
    runs unconditionally — the manifest re-stamp downstream needs a
    record for every generated file even when its bytes are unchanged
    this pass. Without the unconditional record, the re-stamp would
    drop the entry and the next ``--update`` would re-classify the
    file as untracked.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    new_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if target.is_file():
        # Compare via decoded text so the hashes match iff the next
        # write_text() would produce a logically-identical file. See
        # the function docstring for the line-ending rationale.
        try:
            existing_sha = hashlib.sha256(
                target.read_text(encoding="utf-8").encode("utf-8")
            ).hexdigest()
        except (UnicodeDecodeError, OSError):
            existing_sha = ""
        if existing_sha == new_sha:
            # Content unchanged — skip the write. Provenance is still
            # recorded below so the manifest carries the entry.
            if collector is not None:
                collector.record(
                    target,
                    origin="base-template",
                    template_name="_codegen",
                    template_version=None,
                )
            return
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
