"""Invariants for the ``agent_agui`` fragment (AG-UI SSE agent endpoint).

The ``agent_agui`` fragment serves the canonical AG-UI Server-Sent-Events
transport at ``POST /api/v1/agent`` — the endpoint the generated frontend
(``useAgentClient`` on ``canvas-core``) actually POSTs ``RunAgentInput`` to.
It reuses the pydantic-ai agent build + ``tool_registry`` from the ``agent``
fragment, so it is gated by ``agent.llm`` (which provides that agent).

This file gates:
  - ``agent_agui`` is registered in ``FRAGMENT_REGISTRY`` and ``agent.llm``
    enables it (alongside the existing ``agent`` fragment);
  - it resolves for a Python backend with ``agent.llm=true``;
  - a dry-run render emits ``src/app/api/v1/endpoints/agui.py`` +
    ``AGENT_AGUI_HARDENING.md``, the rendered ``api.py`` registers the agui
    router at prefix ``"/agent"``, and pyproject pins the bumped
    ``pydantic-ai-slim[ag-ui...]`` dependency;
  - the rendered ``agui.py`` references ``AGUIAdapter.dispatch_request`` and is
    auth-gated (``get_current_user``) when auth is present;
  - the legacy WS endpoint (``agent.py``) STILL renders (we keep it).
"""

from __future__ import annotations

from pathlib import Path

from forge.capability_resolver import resolve
from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.fragments import FRAGMENT_REGISTRY
from forge.generator import generate
from forge.options import OPTION_REGISTRY

FRAGMENT_NAME = "agent_agui"
# The exact bumped dependency string — must be identical to the ``agent``
# fragment's pydantic-ai pin (one pyproject = one pydantic-ai).
DEP_STRING = "pydantic-ai-slim[ag-ui,anthropic,openai,google,openrouter]>=1.74,<2"


def _agent_llm_cfg(*, output_dir: str | None = None) -> ProjectConfig:
    """A Python backend with the full agent.llm stack enabled.

    Mirrors the ``full_feature_max`` golden preset's agent wiring:
    agent.streaming + agent.tools + agent.llm + conversation.persistence.
    """
    options = {
        "conversation.persistence": True,
        "agent.streaming": True,
        "agent.tools": True,
        "agent.llm": True,
        "llm.provider": "openai",
    }
    kwargs: dict[str, object] = {}
    if output_dir is not None:
        kwargs["output_dir"] = output_dir
    return ProjectConfig(
        project_name="agui",
        backends=[
            BackendConfig(
                name="api",
                project_name="agui",
                language=BackendLanguage.PYTHON,
                features=["items"],
            )
        ],
        frontend=None,
        options=options,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Registration + option wiring
# --------------------------------------------------------------------------- #


def test_agent_agui_registered() -> None:
    assert FRAGMENT_NAME in FRAGMENT_REGISTRY


def test_agent_agui_python_only() -> None:
    frag = FRAGMENT_REGISTRY[FRAGMENT_NAME]
    assert set(frag.implementations) == {BackendLanguage.PYTHON}


def test_agent_agui_depends_on_agent_and_streaming() -> None:
    frag = FRAGMENT_REGISTRY[FRAGMENT_NAME]
    assert set(frag.depends_on) == {"agent_streaming", "agent"}


def test_agent_agui_dep_string() -> None:
    frag = FRAGMENT_REGISTRY[FRAGMENT_NAME]
    spec = frag.implementations[BackendLanguage.PYTHON]
    assert DEP_STRING in spec.dependencies


def test_agent_and_agent_agui_share_pydantic_ai_pin() -> None:
    """One pyproject pins exactly one pydantic-ai: the ``agent`` and
    ``agent_agui`` fragments must declare the identical dependency."""
    agent_spec = FRAGMENT_REGISTRY["agent"].implementations[BackendLanguage.PYTHON]
    agui_spec = FRAGMENT_REGISTRY[FRAGMENT_NAME].implementations[BackendLanguage.PYTHON]
    assert DEP_STRING in agent_spec.dependencies
    assert DEP_STRING in agui_spec.dependencies


def test_agent_llm_enables_agent_agui() -> None:
    opt = OPTION_REGISTRY["agent.llm"]
    enabled = opt.enables.get(True, ())
    assert "agent" in enabled
    assert FRAGMENT_NAME in enabled


# --------------------------------------------------------------------------- #
# Resolver
# --------------------------------------------------------------------------- #


def test_agent_agui_resolves_with_agent_llm() -> None:
    plan = resolve(_agent_llm_cfg())
    names = {rf.fragment.name for rf in plan.ordered}
    assert FRAGMENT_NAME in names
    # The fragment it reuses is in the plan too.
    assert "agent" in names


def test_agent_agui_absent_without_agent_llm() -> None:
    """agent.tools alone (no agent.llm) must NOT pull in the SSE endpoint —
    AG-UI needs the pydantic-ai agent that agent.llm provides."""
    cfg = ProjectConfig(
        project_name="noagui",
        backends=[
            BackendConfig(
                name="api",
                project_name="noagui",
                language=BackendLanguage.PYTHON,
                features=["items"],
            )
        ],
        frontend=None,
        options={"agent.tools": True},
    )
    plan = resolve(cfg)
    names = {rf.fragment.name for rf in plan.ordered}
    assert FRAGMENT_NAME not in names


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #


def test_render_emits_agui_endpoint_and_hardening(tmp_path: Path) -> None:
    cfg = _agent_llm_cfg(output_dir=str(tmp_path))
    root = Path(generate(cfg, quiet=True, dry_run=True))
    backend = root / "services" / "api"

    agui = backend / "src/app/api/v1/endpoints/agui.py"
    hardening = backend / "AGENT_AGUI_HARDENING.md"
    assert agui.is_file()
    assert hardening.is_file()

    # The endpoint uses the raw-Request dispatch_request one-liner path.
    agui_src = agui.read_text(encoding="utf-8")
    assert "AGUIAdapter.dispatch_request" in agui_src
    assert "build_agent" in agui_src

    # Auth-gated: same posture as /api/v1/tools.
    assert "get_current_user" in agui_src
    assert "from forge_core.security.auth import get_current_user" in agui_src

    # Router registered at /agent (api_router is at /api/v1 → /api/v1/agent).
    api_py = (backend / "src/app/api/v1/api.py").read_text(encoding="utf-8")
    assert "from app.api.v1.endpoints import agui as agui_endpoint" in api_py
    assert 'prefix="/agent"' in api_py
    assert "agui_endpoint.router" in api_py

    # pyproject pins the bumped pydantic-ai-slim dep (with provider extras).
    pyproject = (backend / "pyproject.toml").read_text(encoding="utf-8")
    assert "pydantic-ai-slim[ag-ui" in pyproject
    # And the legacy WS endpoint is still rendered (we keep it).
    assert (backend / "src/app/api/v1/endpoints/agent.py").is_file()


def test_render_ws_endpoint_still_present(tmp_path: Path) -> None:
    """The SSE endpoint is additive — the WebSocket transport remains."""
    cfg = _agent_llm_cfg(output_dir=str(tmp_path))
    root = Path(generate(cfg, quiet=True, dry_run=True))
    backend = root / "services" / "api"
    agent_ws = backend / "src/app/api/v1/endpoints/agent.py"
    assert agent_ws.is_file()
    api_py = (backend / "src/app/api/v1/api.py").read_text(encoding="utf-8")
    # WS still mounted at /ws.
    assert 'prefix="/ws"' in api_py
