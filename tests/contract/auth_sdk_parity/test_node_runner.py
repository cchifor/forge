"""Node parity runner — Python orchestrator.

Spawns the SDK-shipped vitest test (`test/parity_runner.test.ts`)
with the canonical scenarios JSON via `PARITY_FIXTURES` env var.
Asserts the runner exits 0 — every scenario passed in the Node SDK.

Skipped at collection time when the toolchain isn't ready:
  - ``node`` / ``npx`` not on PATH (most forge dev envs don't have
    Node installed by default)
  - SDK's ``node_modules/`` doesn't exist (consumer hasn't run
    ``npm install`` yet)

Production CI activates the runner by ensuring Node + npm install
have been done in the SDK template directory before pytest runs:

```bash
(cd forge/features/auth/templates/platform_auth_sdk_node/node/files/sdks/platform-auth-node && npm install)
uv run pytest tests/contract/auth_sdk_parity/test_node_runner.py
```

Cross-reference: implementation plan at
``~/.claude/plans/review-the-c-users-chifo-work-platform-a-pure-torvalds.md``
(Phase 9 deliverables).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.contract.auth_sdk_parity.scenarios import scenarios_as_json


REPO_ROOT = Path(__file__).resolve().parents[3]
NODE_SDK_DIR = (
    REPO_ROOT
    / "forge"
    / "features"
    / "auth"
    / "templates"
    / "platform_auth_sdk_node"
    / "node"
    / "files"
    / "sdks"
    / "platform-auth-node"
)


def _toolchain_ready() -> tuple[bool, str]:
    """Return (ready, reason). Reason explains why we're skipping."""
    if not NODE_SDK_DIR.is_dir():
        return False, f"Node SDK directory missing: {NODE_SDK_DIR}"
    if shutil.which("node") is None:
        return False, "node not on PATH"
    if shutil.which("npx") is None:
        return False, "npx not on PATH"
    if not (NODE_SDK_DIR / "node_modules").is_dir():
        return (
            False,
            f"node_modules/ missing — run `cd {NODE_SDK_DIR} && npm install` first",
        )
    return True, ""


# Skip the whole module at collection time when the toolchain isn't
# ready — keeps forge's normal pytest invocation green even on dev
# machines without Node.
_ready, _skip_reason = _toolchain_ready()
pytestmark = pytest.mark.skipif(not _ready, reason=_skip_reason)


def test_node_sdk_passes_all_parity_scenarios(tmp_path: Path) -> None:
    """Every cross-SDK scenario must verify identically in the Node
    SDK as in Python. Caught Node-side drifts (Phase 4 follow-up
    that aligned `StaticMayActPolicy`'s keying with Python's canonical
    `audience → actors` shape) surface here as scenario failures
    BEFORE they ship to consumers."""
    fixtures_path = tmp_path / "scenarios.json"
    fixtures_path.write_text(json.dumps(scenarios_as_json()), encoding="utf-8")

    # The SDK ships a vitest test that loads the fixtures path from
    # PARITY_FIXTURES. We invoke vitest from inside the SDK directory
    # so the relative imports (`../src/index.js`) resolve.
    env = {
        **subprocess.os.environ,
        "PARITY_FIXTURES": str(fixtures_path),
        # Force vitest to colorless output for cleaner CI logs.
        "FORCE_COLOR": "0",
    }
    completed = subprocess.run(
        ["npx", "vitest", "run", "test/parity_runner.test.ts", "--reporter=basic"],
        cwd=NODE_SDK_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if completed.returncode != 0:
        pytest.fail(
            f"Node parity runner failed (exit {completed.returncode})\n\n"
            f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}"
        )
