"""Run the generated Gatekeeper and Python SDK together, with real JWT crypto.

Redis is emulated in-process; OIDC JWKS uses an HTTP transport fixture. No
external issuer, network service or Docker daemon is required.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.generator import generate

pytestmark = pytest.mark.e2e


def test_generated_auth_contract(tmp_path: Path):
    config = ProjectConfig(
        project_name="auth-contract",
        output_dir=tmp_path,
        include_keycloak=True,
        backends=[
            BackendConfig(
                name="orders",
                language=BackendLanguage.PYTHON,
                server_port=5020,
                depends_on=["inventory"],
            ),
            BackendConfig(name="inventory", language=BackendLanguage.PYTHON, server_port=5030),
        ],
        options={"auth.api_keys": True, "auth.service_discovery": True},
    )
    root = generate(config, quiet=True, dry_run=True)
    gatekeeper = root / "deploy/infra/gatekeeper"
    script = Path(__file__).resolve().parents[1] / "runtime/gatekeeper_contract.py"
    rendered_script = gatekeeper / "tests/test_auth_contract.py"
    rendered_script.parent.mkdir(exist_ok=True)
    shutil.copyfile(script, rendered_script)
    env = {
        **os.environ,
        "ENV": "test",
        "OTEL_TRACES_ENABLED": "false",
        "OTEL_METRICS_ENABLED": "false",
        "GATEKEEPER_CLIENT_SECRET": "contract-only-secret",
        "PYTHONPATH": os.pathsep.join(
            [str(gatekeeper / "src"), str(root / "packages/platform-auth/src")]
        ),
    }
    try:
        result = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(gatekeeper),
                "--group",
                "dev",
                "--with-editable",
                str(root / "packages/platform-auth"),
                "pytest",
                "-c",
                str(gatekeeper / "pyproject.toml"),
                str(rendered_script),
                "-q",
                "--no-cov",
            ],
            cwd=gatekeeper,
            env=env,
            capture_output=True,
            text=True,
            timeout=240,
        )
    finally:
        shutil.rmtree(root.parent)
    assert result.returncode == 0, result.stdout + result.stderr
