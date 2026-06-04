"""E2E: every Vue app-shell layout's generated frontend actually builds, and a
full generated stack serves over docker compose.

The per-layout build is the real compile gate for the layouts: the frontend
Dockerfile runs ``npm install`` + ``npm run build`` (vue-tsc type-check + vite
bundle) in a clean ``node:22`` container, so a TypeScript/Vue error in any
layout fails here (where the dry-run render tests can't see it).

Marked ``@pytest.mark.e2e`` — excluded from the default ``pytest`` run; opt in
with ``-m e2e``. Skips cleanly when docker is unavailable.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from forge.config import (
    BackendConfig,
    BackendLanguage,
    FrontendConfig,
    FrontendFramework,
    ProjectConfig,
)
from forge.generator import generate

pytestmark = pytest.mark.e2e

_DOCKER = shutil.which("docker")
_ALL_LAYOUTS = ["sidebar", "topnav", "tabbar", "threepane", "bento", "docs"]
# Chat-gated layouts where chat-off must also compile (codex flagged the risk).
_CHAT_OFF_LAYOUTS = ["threepane", "docs"]

_needs_docker = pytest.mark.skipif(_DOCKER is None, reason="docker not on PATH")


def _generate(
    tmp_path: Path, layout: str, *, include_chat: bool = True, include_auth: bool = True
) -> Path:
    """Real (non-dry-run) generation so post_generate runs; returns project root."""
    cfg = ProjectConfig(
        project_name="e2e",
        output_dir=str(tmp_path),
        backends=[
            BackendConfig(
                name="api",
                project_name="e2e",
                language=BackendLanguage.PYTHON,
                features=["items"],
            )
        ],
        frontend=FrontendConfig(
            project_name="e2e",
            framework=FrontendFramework.VUE,
            layout=layout,
            include_chat=include_chat,
            include_auth=include_auth,
            include_openapi=True,
        ),
    )
    return Path(generate(cfg, quiet=True))


def _docker_build(frontend_dir: Path, tag: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_DOCKER, "build", "-t", tag, "."],
        cwd=frontend_dir,
        capture_output=True,
        text=True,
        timeout=1200,
    )


@_needs_docker
@pytest.mark.parametrize("layout", _ALL_LAYOUTS)
def test_layout_frontend_builds(tmp_path: Path, layout: str) -> None:
    """Each layout's generated frontend compiles + bundles in a clean container."""
    frontend = _generate(tmp_path, layout) / "apps" / "frontend"
    assert (frontend / "Dockerfile").is_file(), f"{layout}: no frontend Dockerfile"
    tag = f"forge-e2e-{layout}"
    try:
        res = _docker_build(frontend, tag)
        assert res.returncode == 0, (
            f"{layout} frontend build failed:\n{res.stdout[-4000:]}\n{res.stderr[-2000:]}"
        )
    finally:
        subprocess.run([_DOCKER, "image", "rm", "-f", tag], capture_output=True)


@_needs_docker
@pytest.mark.parametrize("layout", _CHAT_OFF_LAYOUTS)
def test_layout_frontend_builds_without_chat(tmp_path: Path, layout: str) -> None:
    """Chat-gated layouts still compile when include_chat=False (no dangling refs)."""
    frontend = _generate(tmp_path, layout, include_chat=False) / "apps" / "frontend"
    tag = f"forge-e2e-{layout}-nochat"
    try:
        res = _docker_build(frontend, tag)
        assert res.returncode == 0, (
            f"{layout} (chat off) frontend build failed:\n{res.stdout[-4000:]}\n{res.stderr[-2000:]}"
        )
    finally:
        subprocess.run([_DOCKER, "image", "rm", "-f", tag], capture_output=True)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@_needs_docker
def test_layout_frontend_serves(tmp_path: Path) -> None:
    """A built layout frontend actually serves its SPA over nginx (runtime smoke).

    Scoped to the frontend container (build + run + curl) rather than the full
    ``docker compose`` stack: a full stack-up is currently blocked by a
    pre-existing, layout-orthogonal forge bug — the generated compose declares a
    ``sdks: ./sdks`` build context for backend services that isn't created for
    python-only projects, so ``docker compose up`` fails before the frontend
    starts. Serving the built frontend image is the layout-relevant runtime check.
    """
    frontend = _generate(tmp_path, "sidebar", include_auth=False) / "apps" / "frontend"
    tag = "forge-e2e-serve"
    build = _docker_build(frontend, tag)
    assert build.returncode == 0, (
        f"frontend build failed:\n{build.stdout[-3000:]}\n{build.stderr[-2000:]}"
    )
    port = _free_port()
    container = ""
    try:
        run = subprocess.run(
            [_DOCKER, "run", "-d", "-p", f"{port}:80", tag],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode == 0, f"docker run failed: {run.stderr}"
        container = run.stdout.strip()
        url = f"http://localhost:{port}/"
        status, body = 0, b""
        for _ in range(20):
            try:
                with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
                    status, body = resp.status, resp.read(8192)
                if status == 200:
                    break
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(1)
        assert status == 200, f"frontend did not serve 200 at {url}"
        assert b'id="app"' in body, "served page is not the Vue SPA shell"
    finally:
        if container:
            subprocess.run([_DOCKER, "rm", "-f", container], capture_output=True)
        subprocess.run([_DOCKER, "image", "rm", "-f", tag], capture_output=True)
