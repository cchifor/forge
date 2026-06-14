"""Compose hardening: backends declare the infra they need + python carries port.

Two regressions this locks in (no golden uses ``--platform``, so the
multitenant-saas topology these exercise was never snapshot-guarded):

* a backend whose app-template declares ``requires_services`` (the TMS outbox
  relay needs Redis) gets a healthcheck-gated ``depends_on`` so it doesn't
  race the infra container and crash-loop;
* every python backend carries ``APP__SERVER__PORT`` so a non-default port
  binds correctly (Node/Rust already did; python silently bound 5000).
"""

from __future__ import annotations

import re
from pathlib import Path

from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.docker_manager import render_compose


def _tms_platform_config(tmp_path: Path) -> ProjectConfig:
    return ProjectConfig(
        project_name="Mt",
        output_dir=str(tmp_path),
        include_keycloak=True,  # renders the redis service the TMS depends on
        backends=[
            BackendConfig(
                name="tms",
                project_name="Mt",
                language=BackendLanguage.PYTHON,
                features=["items"],
                server_port=5010,
                app_template="tenant-management-service",
            ),
            BackendConfig(
                name="app",
                project_name="Mt",
                language=BackendLanguage.PYTHON,
                features=["items"],
                server_port=5020,
            ),
        ],
    )


def _service_block(compose: str, name: str) -> str:
    """The lines of one compose service (from ``  name:`` to the next ``  x:``)."""
    out: list[str] = []
    capturing = False
    for line in compose.splitlines():
        if re.match(rf"^  {re.escape(name)}:\s*$", line):
            capturing = True
            out.append(line)
            continue
        if capturing and re.match(r"^  \S", line):
            break
        if capturing:
            out.append(line)
    return "\n".join(out)


def test_tms_depends_on_redis_healthy(tmp_path):
    compose = render_compose(_tms_platform_config(tmp_path), tmp_path).read_text("utf-8")
    tms = _service_block(compose, "tms")
    assert "redis:\n        condition: service_healthy" in tms, tms


def test_plain_backend_does_not_depend_on_redis(tmp_path):
    compose = render_compose(_tms_platform_config(tmp_path), tmp_path).read_text("utf-8")
    app = _service_block(compose, "app")
    assert "redis:" not in app, app


def test_python_backends_carry_server_port(tmp_path):
    compose = render_compose(_tms_platform_config(tmp_path), tmp_path).read_text("utf-8")
    assert 'APP__SERVER__PORT: "5010"' in _service_block(compose, "tms")
    assert 'APP__SERVER__PORT: "5020"' in _service_block(compose, "app")


def test_no_depends_on_unrendered_service(tmp_path):
    # database.mode keeps postgres+migrate; without keycloak there is NO redis
    # service, so a TMS backend must NOT emit a redis dependency that would make
    # `docker compose up` fail with "depends on undefined service".
    cfg = ProjectConfig(
        project_name="Solo",
        output_dir=str(tmp_path),
        include_keycloak=False,
        backends=[
            BackendConfig(
                name="tms",
                project_name="Solo",
                language=BackendLanguage.PYTHON,
                features=["items"],
                server_port=5010,
                app_template="tenant-management-service",
            ),
        ],
    )
    compose = render_compose(cfg, tmp_path).read_text("utf-8")
    assert "\n  redis:\n" not in compose  # service not rendered
    assert "redis:" not in _service_block(compose, "tms")  # and no dangling dep
