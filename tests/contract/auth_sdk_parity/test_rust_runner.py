"""Rust parity runner — Python orchestrator.

Spawns the SDK-shipped cargo integration test
(`tests/parity_runner.rs`) with the canonical scenarios JSON via
`PARITY_FIXTURES` env var. Asserts the runner exits 0 — every
scenario passed in the Rust SDK.

Skipped at collection time when the toolchain isn't ready:
  - ``cargo`` not on PATH (most forge dev envs don't have Rust
    installed by default)

Unlike the Node runner, no `npm install`-equivalent precondition —
``cargo test`` resolves dependencies lazily on first run.

Production CI activates the runner by installing the Rust toolchain
in the CI image before pytest runs:

```bash
rustup default stable
uv run pytest tests/contract/auth_sdk_parity/test_rust_runner.py
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
RUST_SDK_DIR = (
    REPO_ROOT
    / "forge"
    / "features"
    / "auth"
    / "templates"
    / "platform_auth_sdk_rust"
    / "rust"
    / "files"
    / "packages"
    / "platform-auth-rs"
)


@pytest.fixture(scope="module")
def rust_sdk_sandbox(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Copy the SDK template to a per-module tempdir so cargo can write
    its ``Cargo.lock`` + ``target/`` without polluting the in-repo
    template tree. ``test_golden_snapshots`` would otherwise flag the
    artefacts as drift (CI runs ``test_rust_runner`` before the snapshot
    pass when cargo is on PATH). Module-scoped so the three cargo
    invocations share a warm target dir.
    """
    sandbox = tmp_path_factory.mktemp("platform-auth-rs-sandbox")
    dest = sandbox / "platform-auth-rs"
    shutil.copytree(str(RUST_SDK_DIR), str(dest))
    return dest


def _toolchain_ready() -> tuple[bool, str]:
    """Return (ready, reason). Reason explains why we're skipping."""
    if not RUST_SDK_DIR.is_dir():
        return False, f"Rust SDK directory missing: {RUST_SDK_DIR}"
    if shutil.which("cargo") is None:
        return False, "cargo not on PATH"
    return True, ""


# Skip the whole module at collection time when the toolchain isn't
# ready — keeps forge's normal pytest invocation green even on dev
# machines without Rust.
_ready, _skip_reason = _toolchain_ready()
pytestmark = pytest.mark.skipif(not _ready, reason=_skip_reason)


def test_rust_sdk_passes_all_parity_scenarios(tmp_path: Path, rust_sdk_sandbox: Path) -> None:
    """Every cross-SDK scenario must verify identically in the Rust
    SDK as in Python and Node. Caught Rust-side drifts (e.g. the
    Phase 6 `StaticMayActPolicy` keying alignment) surface here as
    scenario failures BEFORE they ship to consumers."""
    fixtures_path = tmp_path / "scenarios.json"
    fixtures_path.write_text(json.dumps(scenarios_as_json()), encoding="utf-8")

    env = {
        **subprocess.os.environ,
        "PARITY_FIXTURES": str(fixtures_path),
        # Less colour noise in CI logs.
        "CARGO_TERM_COLOR": "never",
    }
    completed = subprocess.run(
        [
            "cargo",
            "test",
            "--features",
            "testing",
            "--test",
            "parity_runner",
            "--",
            "--nocapture",
        ],
        cwd=rust_sdk_sandbox,
        env=env,
        capture_output=True,
        text=True,
        # Cargo's first build resolves the full dep graph (jose-equiv
        # + tokio + reqwest + wiremock + ...). Cold compile easily
        # exceeds 5 min; reused target/ folder cuts to <30s.
        timeout=600,
    )
    if completed.returncode != 0:
        pytest.fail(
            f"Rust parity runner failed (exit {completed.returncode})\n\n"
            f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}"
        )


def test_rust_sdk_axum_layer_integration(rust_sdk_sandbox: Path) -> None:
    """The Tower layer composition (`AuthLayer` + `RequireScope` + the
    `IdentityContext` extractor) must hold end-to-end. The bare-verifier
    parity runner doesn't exercise this path — it only drives
    ``AuthGuard::verify`` directly. This second cargo invocation runs
    the SDK's Axum-flavoured integration tests so a future change that
    breaks layer wiring (e.g., extension binding, skip-list semantics,
    RFC 7807 problem-response shape) surfaces here BEFORE it ships.

    Gated behind both ``axum`` and ``testing`` features — the integration
    test file itself carries ``#![cfg(all(feature = "axum", feature =
    "testing"))]``, so cargo simply doesn't compile it under the bare
    default features.
    """
    completed = subprocess.run(
        [
            "cargo",
            "test",
            "--features",
            "axum,testing",
            "--test",
            "integration_axum",
        ],
        cwd=rust_sdk_sandbox,
        env={**subprocess.os.environ, "CARGO_TERM_COLOR": "never"},
        capture_output=True,
        text=True,
        # Reuses target/ from the parity-runner test above when both
        # land in the same pytest run, so warm-cache invocation is <30s.
        timeout=600,
    )
    if completed.returncode != 0:
        pytest.fail(
            f"Rust integration_axum tests failed "
            f"(exit {completed.returncode})\n\n"
            f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}"
        )


def test_rust_sdk_audit_callback_integration(rust_sdk_sandbox: Path) -> None:
    """The audit-callback hook fires on the allow path with the
    cross-language record shape (matching Python ``_emit_audit`` and
    Node ``_emitAudit``).

    Behavioural verification — pins:
      - allow path emits exactly one record per verified token
      - record carries ``decision``, ``audience``, ``audiences``,
        ``ts_unix``, ``tenant_id``, ``subject``, sorted ``scopes``,
        ``jti``, ``iss``
      - missing callback is a no-op (no panic, no allocation)
      - deny path is currently a no-op (cross-SDK forward-compat)
      - act-chain immediate-actor surfaces in the record

    Gated on ``testing`` only — the audit module is framework-agnostic,
    no axum needed.
    """
    completed = subprocess.run(
        [
            "cargo",
            "test",
            "--features",
            "testing",
            "--test",
            "audit_callback",
        ],
        cwd=rust_sdk_sandbox,
        env={**subprocess.os.environ, "CARGO_TERM_COLOR": "never"},
        capture_output=True,
        text=True,
        timeout=600,
    )
    if completed.returncode != 0:
        pytest.fail(
            f"Rust audit_callback tests failed "
            f"(exit {completed.returncode})\n\n"
            f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}"
        )
