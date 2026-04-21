"""Codegen pipeline — runs every schema-driven emitter during `forge new`.

Called once from ``generator.generate`` after all templates have been
rendered and before ``forge.toml`` is stamped. Each emit-site decides
which targets it writes based on the project's frontend + backend
choices.

Concretely:

    1. UI protocol schemas → Vue/Svelte types.ts, Flutter agent_state.dart,
       Python Pydantic models under each backend.
    2. Canvas component manifest → per-frontend `canvas.manifest.json`.
    3. Shared enums → Python/TS/Dart bindings placed next to the
       consuming code.
    4. Domain DSL → per-backend models + a merged OpenAPI components
       bundle (consumed by the frontend OpenAPI codegen).

All outputs are recorded in the provenance manifest with
``origin='base-template'`` since they're authoritative forge outputs,
not fragment overlays.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from forge.config import ProjectConfig
    from forge.provenance import ProvenanceCollector


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
    _emit_shared_enums(config, project_root, collector)


def _emit_ui_protocol(
    config: ProjectConfig,
    project_root: Path,
    collector: ProvenanceCollector | None,
) -> None:
    """Regenerate UI-protocol types for each frontend + Python backend."""
    schemas = load_ui_schemas(UI_PROTOCOL_ROOT)
    if not schemas:
        return

    frontend = config.frontend
    if frontend and frontend.framework == FrontendFramework.VUE:
        target = (
            project_root
            / config.frontend_slug
            / "src"
            / "features"
            / "ai_chat"
            / "ui_protocol.gen.ts"
        )
        _write(target, emit_typescript(schemas), collector)
    elif frontend and frontend.framework == FrontendFramework.SVELTE:
        target = (
            project_root
            / config.frontend_slug
            / "src"
            / "lib"
            / "features"
            / "chat"
            / "ui_protocol.gen.ts"
        )
        _write(target, emit_typescript(schemas), collector)
    elif frontend and frontend.framework == FrontendFramework.FLUTTER:
        target = (
            project_root
            / config.frontend_slug
            / "lib"
            / "src"
            / "features"
            / "chat"
            / "domain"
            / "ui_protocol.gen.dart"
        )
        _write(target, emit_dart(schemas), collector)

    # Python backends get Pydantic models too.
    for bc in config.backends:
        if bc.language is not BackendLanguage.PYTHON:
            continue
        target = (
            project_root
            / "services"
            / bc.name
            / "src"
            / "app"
            / "domain"
            / "ui_protocol.py"
        )
        _write(target, emit_pydantic(schemas), collector)


def _emit_canvas_manifests(
    config: ProjectConfig,
    project_root: Path,
    collector: ProvenanceCollector | None,
) -> None:
    """Write ``canvas.manifest.json`` into each frontend's public dir.

    The manifest is read at runtime (dev) to validate backend-emitted
    payloads match the component's declared props schema.
    """
    frontend = config.frontend
    if frontend is None or frontend.framework == FrontendFramework.NONE:
        return
    components = load_canvas_components()
    manifest_body = json.dumps(build_canvas_manifest(components), indent=2) + "\n"

    if frontend.framework in (FrontendFramework.VUE, FrontendFramework.SVELTE):
        target = project_root / config.frontend_slug / "public" / "canvas.manifest.json"
    else:
        target = project_root / config.frontend_slug / "assets" / "canvas.manifest.json"
    _write(target, manifest_body, collector)


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

    for enum_file in sorted(_ENUMS_ROOT.glob("*.yaml")):
        spec = load_enum_yaml(enum_file)
        targets = emit_enum_all(spec)

        # Python backends
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

        # Frontends
        frontend = config.frontend
        if frontend is None or frontend.framework == FrontendFramework.NONE:
            continue
        if frontend.framework == FrontendFramework.VUE:
            path = (
                project_root
                / config.frontend_slug
                / "src"
                / "shared"
                / "enums"
                / f"{enum_file.stem}.ts"
            )
            _write(path, targets["typescript"], collector)
        elif frontend.framework == FrontendFramework.SVELTE:
            path = (
                project_root
                / config.frontend_slug
                / "src"
                / "lib"
                / "shared"
                / "enums"
                / f"{enum_file.stem}.ts"
            )
            _write(path, targets["typescript"], collector)
        elif frontend.framework == FrontendFramework.FLUTTER:
            path = (
                project_root
                / config.frontend_slug
                / "lib"
                / "src"
                / "shared"
                / "enums"
                / f"{enum_file.stem}.dart"
            )
            _write(path, targets["dart"], collector)


def _write(
    target: Path,
    content: str,
    collector: ProvenanceCollector | None,
) -> None:
    """Write ``content`` to ``target`` and record base-template provenance."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    if collector is not None:
        collector.record(target, origin="base-template")
