"""Standalone-build gate (P5): a generated Python project builds with NO weld.

The keystone of the weld-decoupling effort: a generated project must resolve,
type-check, and pass its own test suite *without* any ``weld-*`` package being
installable — the always-shipped ``forge-core`` SDK (vendored inside each
backend at ``sdks/forge-core/``) is enough. Unlike :mod:`test_full_generation`,
this test deliberately does NOT inject the matrix weld stubs: if the generated
project still imports weld anywhere, ``uv sync`` / ``pytest`` would fail.

Two postures are exercised, both of which must come out weld-free:

* **auth off** (``auth.mode=none``) — the minimal default project.
* **auth.mode=generate** — the full platform-auth stack (SDK at
  ``sdks/platform-auth/`` + middleware fragment + gatekeeper-provider config).

Marked ``@pytest.mark.e2e`` (heavy / opt-in like the other scaffold-and-run
tests). Run explicitly with ``pytest -m e2e -k standalone_build``.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from forge.config import (
    BackendConfig,
    BackendLanguage,
    ProjectConfig,
)
from forge.generator import generate

pytestmark = pytest.mark.e2e

TEST_TIMEOUT_S = 600


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    import shutil as _shutil

    resolved = _shutil.which(cmd[0])
    if resolved is not None:
        cmd = [resolved, *cmd[1:]]
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TEST_TIMEOUT_S,
        check=False,
    )


def _python_files(root: Path) -> list[Path]:
    return [
        p for p in root.rglob("*.py") if "__pycache__" not in p.parts and ".venv" not in p.parts
    ]


def _grep_weld(root: Path) -> list[str]:
    """Return every ``import weld`` / ``from weld`` occurrence under ``root``."""
    hits: list[str] = []
    for p in _python_files(root):
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("import weld", "from weld")):
                hits.append(f"{p}:{lineno}:{stripped}")
    # pyproject / lock references too
    for name in ("pyproject.toml", "uv.lock"):
        for p in root.rglob(name):
            if ".venv" in p.parts:
                continue
            text = p.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                if "weld-" in line or "weld_" in line:
                    hits.append(f"{p}:{lineno}:{line.strip()}")
    return hits


def _assert_ast_parses(root: Path) -> None:
    for p in _python_files(root):
        source = p.read_text(encoding="utf-8")
        ast.parse(source, filename=str(p))


def _minimal_config(tmp_path: Path) -> ProjectConfig:
    return ProjectConfig(
        project_name="Standalone Minimal",
        output_dir=str(tmp_path),
        backends=[
            BackendConfig(
                name="svc",
                project_name="Standalone Minimal",
                language=BackendLanguage.PYTHON,
                features=["items"],
                # No sibling sdks/ tree in this standalone tmp build.
                sdk_consumption="none",
            )
        ],
        frontend=None,
    )


def _auth_config(tmp_path: Path) -> ProjectConfig:
    return ProjectConfig(
        project_name="Standalone Auth",
        output_dir=str(tmp_path),
        backends=[
            BackendConfig(
                name="svc",
                project_name="Standalone Auth",
                language=BackendLanguage.PYTHON,
                features=["items"],
                sdk_consumption="none",
            )
        ],
        frontend=None,
        include_keycloak=True,
        options={"auth.mode": "generate", "auth.provider": "gatekeeper"},
    )


def _max_config(tmp_path: Path) -> ProjectConfig:
    """Mirror the ``full_feature_max`` golden preset's heavy backend.

    Every weld-importing feature fragment converted across P5 Stage-2 is in
    play here: conversation.persistence, agent.streaming/tools, rag.reranker
    (transitively rag_pipeline -> conversation_persistence, the
    get_customer_id + tenant-mixin rewires), chat.attachments (file_upload),
    platform.webhooks/admin (webhook model + endpoints), plus the gatekeeper
    auth stack (get_current_user → forge_core.security.auth). If any fragment
    still referenced ``weld``, ``uv sync`` would fail to resolve and/or the
    weld grep below would trip. The Vue frontend the preset ships is omitted
    — the weld-free proof is backend-scoped and the build only exercises the
    Python service.

    NOTE: the golden preset additionally sets ``agent.llm`` + ``llm.provider``;
    those are deliberately OMITTED here. The ``llm_openai`` fragment injects
    ``api_key=_settings.openai_api_key`` into ``container.py`` without
    declaring the matching ``Settings`` field — a pre-existing generated-
    project bug (the same combo ``known-issues.md`` flagged as crashing) that
    the golden snapshot's ``dry_run`` masks because it never imports the
    container. It carries no ``weld`` import and is orthogonal to the P5
    weld-free surface, so including it would only fail this build on an
    unrelated defect.
    """
    return ProjectConfig(
        project_name="Standalone Max",
        output_dir=str(tmp_path),
        backends=[
            BackendConfig(
                name="svc",
                project_name="Standalone Max",
                language=BackendLanguage.PYTHON,
                features=["items", "orders"],
                sdk_consumption="none",
            )
        ],
        frontend=None,
        include_keycloak=True,
        options={
            "auth.mode": "generate",
            "auth.provider": "gatekeeper",
            "observability.tracing": True,
            "observability.health": True,
            "middleware.rate_limit": True,
            "middleware.security_headers": True,
            "middleware.pii_redaction": True,
            "conversation.persistence": True,
            "agent.streaming": True,
            "agent.tools": True,
            "rag.reranker": True,
            "chat.attachments": True,
            "platform.webhooks": True,
            "platform.admin": True,
            "platform.cli_extensions": True,
            "platform.agents_md": True,
        },
    )


def _airlock_config(tmp_path: Path) -> ProjectConfig:
    """A weld-free integration feature (Airlock client) on the minimal base.

    Airlock exercises four of the six FORGE anchors that were missing from
    the base Python template until the events/streaming/connectors/airlock/mcp
    fragments could finally generate: ``IOC_INFRA_IMPORTS`` +
    ``IOC_INFRA_PROVIDERS`` (the ``AsyncAirlockClient`` DI provider) and
    ``CONFIG_DOMAIN_FIELDS`` + ``CONFIG_DOMAIN_ROOT`` (the ``AirlockSettings``
    nested config). It is the only one of the five whose provider snippet
    imports every type it annotates, so it is the case that builds AND imports
    cleanly end-to-end. The sibling fragments hit pre-existing, anchor-
    orthogonal defects on a full import (events/streaming providers annotate
    ``EventBus`` / ``AsyncEngine`` without importing them — dishka's
    ``UndefinedTypeAnalysisError``; connectors/events_outbox/mcp ship
    ``*.py.jinja`` files the fragment render path never strips to ``*.py``).
    Those are tracked separately; this gate proves the anchors themselves are
    placed correctly by driving the full uv-sync + import for the clean case.
    """
    return ProjectConfig(
        project_name="Standalone Airlock",
        output_dir=str(tmp_path),
        backends=[
            BackendConfig(
                name="svc",
                project_name="Standalone Airlock",
                language=BackendLanguage.PYTHON,
                features=["items"],
                sdk_consumption="none",
            )
        ],
        frontend=None,
        options={"airlock.client": True},
    )


def _build_and_test(backend_dir: Path) -> None:
    """uv sync (no weld available) + run the generated project's pytest."""
    sync = _run(["uv", "sync"], cwd=backend_dir)
    assert sync.returncode == 0, f"uv sync failed (weld-free):\n{sync.stderr}"
    result = _run(["uv", "run", "pytest", "-x", "--no-cov", "-q"], cwd=backend_dir)
    assert result.returncode == 0, (
        f"generated python backend tests failed:\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def test_minimal_project_builds_weld_free(
    tmp_path: Path, require_uv: None, require_git: None
) -> None:
    """auth.mode=none default project: zero weld, deps resolve, tests pass."""
    project_root = generate(_minimal_config(tmp_path), quiet=True)

    weld_hits = _grep_weld(project_root)
    assert not weld_hits, "weld references in a minimal project:\n" + "\n".join(weld_hits)
    _assert_ast_parses(project_root)

    backend_dir = project_root / "services" / "svc"
    assert backend_dir.is_dir()
    _build_and_test(backend_dir)


def test_auth_generate_project_builds_weld_free(
    tmp_path: Path, require_uv: None, require_git: None
) -> None:
    """auth.mode=generate (gatekeeper) project: zero weld, deps resolve, tests pass."""
    project_root = generate(_auth_config(tmp_path), quiet=True)

    weld_hits = _grep_weld(project_root)
    assert not weld_hits, "weld references in an auth project:\n" + "\n".join(weld_hits)
    _assert_ast_parses(project_root)

    backend_dir = project_root / "services" / "svc"
    assert backend_dir.is_dir()
    # The platform-auth SDK ships at the project root; it must be present.
    assert (project_root / "sdks" / "platform-auth").is_dir()
    _build_and_test(backend_dir)


def test_airlock_feature_project_builds_and_imports(
    tmp_path: Path, require_uv: None, require_git: None
) -> None:
    """A feature fragment that injects into the previously-anchorless base
    template generates, resolves weld-free, AST-parses, and *imports* — proving
    the IOC_INFRA_* and CONFIG_DOMAIN_* anchors are placed where the injected
    DI provider + nested config are valid. Import runs under ``ENV=development``
    so the production secret-key guard (an unrelated base-template posture
    check) does not mask the wiring result."""
    import os

    project_root = generate(_airlock_config(tmp_path), quiet=True)

    weld_hits = _grep_weld(project_root)
    assert not weld_hits, "weld references in an airlock project:\n" + "\n".join(weld_hits)
    _assert_ast_parses(project_root)

    backend_dir = project_root / "services" / "svc"
    assert backend_dir.is_dir()
    sync = _run(["uv", "sync"], cwd=backend_dir)
    assert sync.returncode == 0, f"uv sync failed (weld-free):\n{sync.stderr}"

    env = {**os.environ, "ENV": "development"}
    imp = subprocess.run(
        ["uv", "run", "python", "-c", "import app.main"],
        cwd=str(backend_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TEST_TIMEOUT_S,
        check=False,
        env=env,
    )
    assert imp.returncode == 0, (
        f"airlock-wired app failed to import:\nSTDOUT:\n{imp.stdout}\nSTDERR:\n{imp.stderr}"
    )
    # The provider + nested config landed at valid AST positions.
    infra = (backend_dir / "src/app/core/ioc/infra.py").read_text(encoding="utf-8")
    assert "def airlock_client(" in infra
    domain = (backend_dir / "src/app/core/config/domain.py").read_text(encoding="utf-8")
    assert "airlock: AirlockSettings = AirlockSettings()" in domain


def test_full_feature_max_project_builds_weld_free(
    tmp_path: Path, require_uv: None, require_git: None
) -> None:
    """The P5 weld-free capstone: a *fully loaded* project (the
    ``full_feature_max`` feature union — every converted Stage-2 fragment plus
    the gatekeeper auth stack) resolves, parses, and passes its own pytest with
    NO ``weld-*`` package installable. Proves the last weld imports are gone
    across the heavy feature set, not just the minimal/auth baselines."""
    project_root = generate(_max_config(tmp_path), quiet=True)

    weld_hits = _grep_weld(project_root)
    assert not weld_hits, "weld references in a full_feature_max project:\n" + "\n".join(weld_hits)
    _assert_ast_parses(project_root)

    backend_dir = project_root / "services" / "svc"
    assert backend_dir.is_dir()
    # Both always-shipped/auth SDKs vendor in at the project root.
    assert (project_root / "sdks" / "platform-auth").is_dir()
    _build_and_test(backend_dir)
