"""End-to-end: generate a service into a copy of the platform monorepo.

Verifies the 1.2.0-alpha.1 cutover end-to-end: forge generates a Python
service with weld-* deps, drops it into ``platform/services/<name>/``,
and the platform's own ``mise run lint && mise run ty && mise run test``
gates pass on the generated tree.

Slow (~3-5 min wall clock). Gated behind ``FORGE_E2E_PLATFORM=1`` so it
doesn't run in the default ``pytest -m e2e`` sweep — the platform tree
is a sibling working copy, not something CI clones.

Run explicitly with::

    FORGE_E2E_PLATFORM=1 FORGE_PLATFORM_PATH=/path/to/platform \\
        pytest tests/e2e/test_platform_drop_in.py -v -s
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.generator import generate

# How long to wait for each mise task. The platform monorepo is large
# and `mise run lint` walks every service.
TASK_TIMEOUT_S = 600


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("FORGE_E2E_PLATFORM") != "1",
        reason="Set FORGE_E2E_PLATFORM=1 + FORGE_PLATFORM_PATH=/path/to/platform to run.",
    ),
]


def _platform_root() -> Path:
    raw = os.environ.get("FORGE_PLATFORM_PATH")
    if not raw:
        pytest.skip("FORGE_PLATFORM_PATH unset")
    root = Path(raw).resolve()
    if not (root / "packages" / "weld-core" / "pyproject.toml").is_file():
        pytest.skip(
            f"{root} does not look like a platform monorepo "
            "(missing sdks/weld-core/pyproject.toml)."
        )
    return root


def _mise(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a mise task. Skips the test if mise is not installed — we don't
    want to fail the e2e in environments that haven't installed the
    platform's full toolchain."""

    resolved = shutil.which("mise")
    if resolved is None:
        pytest.skip("mise not on PATH")
    return subprocess.run(
        [resolved, "run", *cmd],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=TASK_TIMEOUT_S,
    )


def test_python_service_drops_into_platform(tmp_path: Path) -> None:
    """Generate a service into a copy of platform/services/ and exercise
    mise lint + ty + test against the result.

    Uses a tmp_path copy of the platform tree so the test never mutates
    the developer's working copy. Symlinks ``sdks/`` instead of copying
    to keep the test under a couple seconds of setup.
    """

    src_root = _platform_root()
    work_root = tmp_path / "platform"
    work_root.mkdir()

    # Reuse sdks/ via symlink — read-only, the test never writes inside.
    # Everything else gets a shallow copy so generate() can write into it.
    for entry in src_root.iterdir():
        target = work_root / entry.name
        if entry.name == "sdks":
            target.symlink_to(entry, target_is_directory=True)
        elif entry.name in {"node_modules", ".venv", "htmlcov", "dist"}:
            continue  # noisy build artifacts
        elif entry.is_dir():
            shutil.copytree(entry, target, symlinks=True)
        else:
            shutil.copy2(entry, target)

    services_root = work_root / "services"
    services_root.mkdir(exist_ok=True)

    project = ProjectConfig(
        project_name="forge_e2e_smoke",
        output_dir=services_root,
        backends=[
            BackendConfig(
                name="forge_e2e_smoke",
                language=BackendLanguage.PYTHON,
                options={
                    "sdk_consumption": "monorepo",
                    "weld_base_sdks": "auth,core,fastapi,observability,http-client,events",
                    "events.bus": "postgres_notify",
                    "events.outbox": True,
                    "streaming.sse": True,
                },
            )
        ],
    )

    generate(project)

    service_dir = services_root / "forge_e2e_smoke"
    assert (service_dir / "pyproject.toml").is_file(), "pyproject not emitted"
    assert (service_dir / "Dockerfile").is_file(), "Dockerfile not emitted"
    assert (service_dir / "entrypoint.sh").is_file(), "entrypoint.sh not emitted"
    assert not (service_dir / "src" / "service").exists(), (
        "src/service shim should be gone in 1.2 with sdk_consumption=monorepo"
    )

    # Confirm weld-* deps were declared with [tool.uv.sources]
    pyproject = (service_dir / "pyproject.toml").read_text()
    for sdk in ("weld-auth", "weld-core", "weld-fastapi", "weld-events"):
        assert sdk in pyproject, f"{sdk} missing from generated pyproject"
    assert "[tool.uv.sources]" in pyproject
    assert "../../packages/weld-" in pyproject

    # Platform-level gates. Each is best-effort — the test xfails on
    # missing toolchain instead of red, because the platform tree is
    # a developer-machine artifact and not every CI runner has uv +
    # ty + mise installed.
    for task in (
        ["lint", "--", "services/forge_e2e_smoke"],
        ["ty", "--", "services/forge_e2e_smoke"],
        ["test", "--", "services/forge_e2e_smoke"],
    ):
        result = _mise(task, work_root)
        assert result.returncode == 0, (
            f"mise run {' '.join(task)} failed:\n"
            f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
        )
