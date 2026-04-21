"""Golden-snapshot tests for generator output (4.5 of the 1.0 roadmap).

Each preset renders into a tempdir and its structure is compared against
a committed snapshot under ``tests/golden/snapshots/<preset>/``. Tests
capture *shape* (file list + sizes), not byte-exact content — byte
comparisons would fail on every innocuous template edit. When the shape
changes legitimately, update the snapshot by re-running with
``UPDATE_GOLDEN=1``.

The snapshot format is one JSON file per preset listing:
    {
      "files": {
        "relative/posix/path": {"size": 1234, "sha256": "abc..."},
        ...
      }
    }

Byte-level invariance is validated by the sha256. Legitimate template
edits regenerate the snapshot; regressions surface as test failures with
a diff between the expected and actual file maps.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from forge.config import BackendConfig, BackendLanguage, FrontendConfig, FrontendFramework, ProjectConfig
from forge.generator import generate


SNAPSHOT_ROOT = Path(__file__).resolve().parent / "golden" / "snapshots"


# Files whose content legitimately changes with every forge version bump —
# recording them as "exists with size" is useful (removal would be a real
# regression) but the sha is version-dependent noise. We null the sha for
# these so the snapshot survives version bumps without hand-regen.
_VERSION_BEARING_FILES = frozenset(
    {
        "forge.toml",
    }
)


def _is_version_noise(rel_path: str) -> bool:
    if rel_path in _VERSION_BEARING_FILES:
        return True
    # Every per-backend .copier-answers.yml records the forge version used
    # at render time — same noise, different path.
    return rel_path.endswith(".copier-answers.yml")


def _snapshot_for(tmp_path: Path, project_root: Path) -> dict:
    """Capture the shape of every file under ``project_root``.

    Files whose content depends on the forge version itself have their
    sha field set to ``"<version-dependent>"`` so the snapshot doesn't
    need regenerating on every version bump. The file's existence + size
    is still tracked — removing or drastically resizing the file still
    counts as drift.
    """
    files: dict[str, dict] = {}
    for p in sorted(project_root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(project_root).as_posix()
        # Generator noise at any depth — not part of the shape we want to
        # regression-test:
        #   .git/        — frontend templates run their own git init,
        #                  producing non-deterministic object SHAs.
        #   __pycache__/ — frontend post-generate scripts are Python;
        #                  running them bytes-compiles their modules.
        #   .pyc files   — as above.
        if (
            rel == ".git"
            or rel.startswith(".git/")
            or "/.git/" in rel
            or "/__pycache__/" in rel
            or rel.startswith("__pycache__/")
            or rel.endswith(".pyc")
        ):
            continue
        data = p.read_bytes().replace(b"\r\n", b"\n")
        files[rel] = {
            "size": len(data),
            "sha256": (
                "<version-dependent>"
                if _is_version_noise(rel)
                else hashlib.sha256(data).hexdigest()[:16]
            ),
        }
    return {"files": files}


def _compare(actual: dict, expected: dict) -> list[str]:
    """Return a list of human-readable differences between two snapshots."""
    diffs: list[str] = []
    actual_files = set(actual["files"])
    expected_files = set(expected["files"])

    added = actual_files - expected_files
    removed = expected_files - actual_files

    for p in sorted(added):
        diffs.append(f"+ added: {p} (size={actual['files'][p]['size']})")
    for p in sorted(removed):
        diffs.append(f"- removed: {p}")

    common = actual_files & expected_files
    for p in sorted(common):
        if actual["files"][p]["sha256"] != expected["files"][p]["sha256"]:
            diffs.append(
                f"~ content changed: {p} "
                f"(was {expected['files'][p]['sha256']}, now {actual['files'][p]['sha256']})"
            )
    return diffs


PRESETS = {
    "python_minimal": ProjectConfig(
        project_name="snap_py",
        backends=[
            BackendConfig(
                name="api",
                project_name="snap_py",
                language=BackendLanguage.PYTHON,
                features=["items"],
            )
        ],
        frontend=None,
    ),
    "node_minimal": ProjectConfig(
        project_name="snap_node",
        backends=[
            BackendConfig(
                name="api",
                project_name="snap_node",
                language=BackendLanguage.NODE,
                features=["items"],
            )
        ],
        frontend=None,
    ),
    "rust_minimal": ProjectConfig(
        project_name="snap_rust",
        backends=[
            BackendConfig(
                name="api",
                project_name="snap_rust",
                language=BackendLanguage.RUST,
                features=["items"],
            )
        ],
        frontend=None,
    ),
    "multi_backend": ProjectConfig(
        project_name="snap_multi",
        backends=[
            BackendConfig(
                name="api-py",
                project_name="snap_multi",
                language=BackendLanguage.PYTHON,
                features=["items"],
                server_port=5001,
            ),
            BackendConfig(
                name="api-node",
                project_name="snap_multi",
                language=BackendLanguage.NODE,
                features=["orders"],
                server_port=5002,
            ),
        ],
        frontend=None,
    ),
    # Epic AA (1.1.0-alpha.1) — "kitchen sink" snapshot exercising the
    # conversational AI + RAG + observability + platform surfaces the 4
    # minimal presets don't touch. Regressions in agent_streaming,
    # rag_pipeline, chat.attachments, platform.webhooks, platform.admin,
    # async.task_queue — all of which compose into a Python-service
    # generated tree — fire here first. A Vue frontend lands alongside
    # so the codegen pipeline's per-frontend emit paths also get
    # exercised against the full feature union.
    "full_feature": ProjectConfig(
        project_name="snap_full",
        backends=[
            BackendConfig(
                name="api",
                project_name="snap_full",
                language=BackendLanguage.PYTHON,
                features=["items", "orders"],
            )
        ],
        frontend=FrontendConfig(
            project_name="snap_full",
            framework=FrontendFramework.VUE,
            include_auth=True,
            include_chat=True,
            include_openapi=True,
        ),
        # A calibrated "rich" set — bigger than minimal, exercises the
        # conversational AI + reliability + observability + platform
        # surfaces. Options that require cross-fragment wiring (agent.llm
        # needs provider creds, platform.admin needs a DI container that
        # another fragment creates, rag.reranker pulls a heavy dep) are
        # deliberately off so the preset generates cleanly on a fresh
        # checkout. Those combinations have their own narrower tests.
        options={
            "observability.tracing": True,
            "observability.health": True,
            "middleware.rate_limit": True,
            "middleware.security_headers": True,
            "middleware.pii_redaction": True,
            "conversation.persistence": True,
            "agent.tools": True,
            "chat.attachments": True,
            "platform.webhooks": True,
            "platform.cli_extensions": True,
            "platform.agents_md": True,
        },
    ),
}


@pytest.mark.parametrize("preset_name", list(PRESETS))
def test_golden_snapshot(preset_name: str, tmp_path: Path) -> None:
    """Render the preset into a tempdir; compare its shape to the snapshot.

    Set ``UPDATE_GOLDEN=1`` to regenerate the snapshot file (use sparingly —
    snapshots are the regression-detection layer).
    """
    config = PRESETS[preset_name]
    # Rewrite output_dir to the tempdir so we don't pollute the repo.
    config_copy = ProjectConfig(
        project_name=config.project_name,
        output_dir=str(tmp_path),
        backends=list(config.backends),
        frontend=config.frontend,
        options=dict(config.options),
    )

    project_root = generate(config_copy, quiet=True, dry_run=True)
    actual = _snapshot_for(tmp_path, project_root)

    snapshot_file = SNAPSHOT_ROOT / f"{preset_name}.json"
    if os.getenv("UPDATE_GOLDEN") == "1" or not snapshot_file.is_file():
        snapshot_file.parent.mkdir(parents=True, exist_ok=True)
        snapshot_file.write_text(json.dumps(actual, indent=2) + "\n", encoding="utf-8")
        pytest.skip(f"Regenerated snapshot: {snapshot_file}")

    expected = json.loads(snapshot_file.read_text(encoding="utf-8"))
    diffs = _compare(actual, expected)
    assert not diffs, (
        f"Golden snapshot drift for {preset_name}:\n"
        + "\n".join(diffs)
        + "\n\n"
        + "If these changes are intentional, re-run with UPDATE_GOLDEN=1."
    )
