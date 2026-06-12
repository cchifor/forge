"""End-to-end coverage for the reference Go backend plugin (#224).

Proves the plugin SDK's ``add_backend`` surface is genuinely functional: a
plugin-registered language (``go``) drives a full ``generate()`` through every
language-agnostic generator path — specifically the four sites that used to
coerce the language string with ``BackendLanguage(...)`` and raise
``ValueError`` on anything but python/node/rust (forge.toml writer, config-file
parser, add-backend command, updater template-version walk). When a Go
toolchain is on PATH, the generated service also compiles + tests green.

The reference plugin lives at ``examples/forge-go-backend/``. We add its
``src/`` to ``sys.path`` and call ``register()`` in-process rather than
requiring a pip install, so the generation assertions run in normal CI as a
crash-site regression guard. The ``go build`` assertion is gated on ``go``
being available (``require_go``); generation itself needs no Go (Copier render
+ a best-effort, tool-absent-tolerant toolchain install).
"""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GO_PLUGIN_SRC = _REPO_ROOT / "examples" / "forge-go-backend" / "src"


@pytest.fixture
def go_backend_registered():
    """Register the reference Go backend into the live registries for the
    test, then scrub the additions so other tests see the built-in-only
    registry. Mirrors the snapshot/restore pattern in
    ``test_plugin_backend_language.py``."""
    if not _GO_PLUGIN_SRC.is_dir():
        pytest.skip(f"reference Go plugin not found at {_GO_PLUGIN_SRC}")
    if str(_GO_PLUGIN_SRC) not in sys.path:
        sys.path.insert(0, str(_GO_PLUGIN_SRC))
    mod = importlib.import_module("forge_go_backend")

    from forge.api import ForgeAPI, PluginRegistration
    from forge.backend_app_templates import BACKEND_APPLICATION_TEMPLATES
    from forge.config import BACKEND_REGISTRY, PLUGIN_LANGUAGES

    reg_snapshot = dict(BACKEND_REGISTRY)
    lang_snapshot = dict(PLUGIN_LANGUAGES)
    app_snapshot = dict(BACKEND_APPLICATION_TEMPLATES)

    api = ForgeAPI(
        PluginRegistration(name="forge-go-backend", module="forge_go_backend")
    )
    mod.register(api)
    try:
        yield
    finally:
        for value in list(PLUGIN_LANGUAGES):
            if value not in lang_snapshot:
                sentinel = PLUGIN_LANGUAGES.pop(value)
                BACKEND_REGISTRY.pop(sentinel, None)
        for key in list(BACKEND_REGISTRY):
            if key not in reg_snapshot:
                BACKEND_REGISTRY.pop(key)
        for key in list(BACKEND_APPLICATION_TEMPLATES):
            if key not in app_snapshot:
                BACKEND_APPLICATION_TEMPLATES.pop(key)


@pytest.fixture
def require_go():
    if shutil.which("go") is None:
        pytest.skip("go toolchain not on PATH")


def _make_go_config(tmp_path: Path):
    from forge.config import BackendConfig, ProjectConfig, resolve_backend_language

    bc = BackendConfig(
        name="api",
        project_name="Go Svc",
        language=resolve_backend_language("go"),  # type: ignore[arg-type]
        features=["items"],
        server_port=8300,
    )
    return ProjectConfig(
        project_name="Go Svc",
        output_dir=str(tmp_path),
        backends=[bc],
        include_keycloak=False,
    )


def test_add_backend_registers_language_and_variant(go_backend_registered: None) -> None:
    """add_backend wires the language into BOTH registries — the spec lookup
    AND the default crud-service application-template variant (so a
    BackendConfig on it validates without the plugin doing it separately)."""
    from forge.backend_app_templates import (
        DEFAULT_BACKEND_TEMPLATE,
        get_backend_application_template,
    )
    from forge.config import (
        BACKEND_REGISTRY,
        available_backend_languages,
        resolve_backend_language,
    )

    go = resolve_backend_language("go")
    assert go in BACKEND_REGISTRY
    assert "go" in available_backend_languages()
    assert get_backend_application_template(go, DEFAULT_BACKEND_TEMPLATE) is not None


def test_go_backend_generates(tmp_path: Path, go_backend_registered: None) -> None:
    """A plugin-language project generates through every language-agnostic
    path (forge.toml writer / provenance / compose) without a crash."""
    from forge.generator import generate

    config = _make_go_config(tmp_path)
    config.validate()

    project_root = generate(config, quiet=True)

    service_dir = project_root / "services" / "api"
    assert (service_dir / "main.go").is_file(), "Go service source missing"
    assert (service_dir / "go.mod").read_text(encoding="utf-8").startswith("module api")
    assert (service_dir / "Dockerfile").is_file()
    # forge.toml's template-version walk (a former crash site) recorded the
    # plugin language's template without raising.
    assert '"go"' in (project_root / "forge.toml").read_text(encoding="utf-8") or (
        "go" in (project_root / "forge.toml").read_text(encoding="utf-8")
    )


def test_go_backend_compiles(
    tmp_path: Path, go_backend_registered: None, require_go: None
) -> None:
    """The generated Go service builds, vets, and tests green — end-to-end
    proof that a plugin backend produces a working project."""
    from forge.generator import generate

    config = _make_go_config(tmp_path)
    config.validate()
    project_root = generate(config, quiet=True)
    service_dir = project_root / "services" / "api"

    for cmd, label in (
        (["go", "build", "./..."], "build"),
        (["go", "vet", "./..."], "vet"),
        (["go", "test", "./..."], "test"),
    ):
        result = subprocess.run(
            cmd, cwd=str(service_dir), capture_output=True, text=True, timeout=300
        )
        assert result.returncode == 0, (
            f"go {label} failed for the generated service:\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
