"""Regression: ``_add_node_deps`` must rewrite ``workspace:*`` to ``file:``.

The auth Node middleware fragment declares a dependency on
``@forge/platform-auth-node@workspace:*``. npm (≤ v10) doesn't support
the ``workspace:`` URL protocol — only pnpm and yarn berry do — so
emitting it verbatim into the consumer's ``package.json`` produces an
``EUNSUPPORTEDPROTOCOL`` failure on ``npm install``. The matrix
nightly runs caught it: see GitHub Actions run 25635489228 (and
every CI run on main since the auth Wave 1 Node middleware landed).

The deps applier now rewrites the ``workspace:`` spec to a relative
``file:`` path pointing at the in-tree SDK at
``<project>/sdks/<unscoped-name>/``. The path is normalized to POSIX
separators so the generated ``package.json`` doesn't differ between
Linux and Windows runners.
"""

from __future__ import annotations

import json
from pathlib import Path

from forge.appliers.deps import _add_node_deps


def _write_pkg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"name": "consumer", "version": "0.0.0", "dependencies": {}}),
        encoding="utf-8",
    )


def test_workspace_spec_rewrites_to_relative_file_path(tmp_path: Path) -> None:
    """Multi-backend layout: backend at services/<name>/, SDK at sdks/<name>/."""
    project = tmp_path / "proj"
    backend_pkg = project / "services" / "node-svc" / "package.json"
    sdk_root = project / "sdks" / "platform-auth-node"
    sdk_root.mkdir(parents=True)
    _write_pkg(backend_pkg)

    _add_node_deps(backend_pkg, ("@forge/platform-auth-node@workspace:*",))

    written = json.loads(backend_pkg.read_text(encoding="utf-8"))
    spec = written["dependencies"]["@forge/platform-auth-node"]
    assert spec == "file:../../sdks/platform-auth-node", (
        f"expected forward-slash relative file: spec, got {spec!r}"
    )


def test_workspace_spec_rewrites_for_single_level_backend(tmp_path: Path) -> None:
    """Single-backend layout: backend at root-of-project, SDK at sdks/<name>/."""
    project = tmp_path / "proj"
    backend_pkg = project / "node-svc" / "package.json"
    (project / "sdks" / "platform-auth-node").mkdir(parents=True)
    _write_pkg(backend_pkg)

    _add_node_deps(backend_pkg, ("@forge/platform-auth-node@workspace:*",))

    spec = json.loads(backend_pkg.read_text(encoding="utf-8"))["dependencies"][
        "@forge/platform-auth-node"
    ]
    assert spec == "file:../sdks/platform-auth-node"


def test_workspace_spec_preserved_when_sdk_missing(tmp_path: Path) -> None:
    """If we can't find the SDK on disk, leave the spec alone.

    npm install will then fail with EUNSUPPORTEDPROTOCOL — the same
    pre-fix failure — which is louder than silently writing a
    file:./missing path that papers over the real configuration bug.
    """
    project = tmp_path / "proj"
    backend_pkg = project / "services" / "node-svc" / "package.json"
    _write_pkg(backend_pkg)

    _add_node_deps(backend_pkg, ("@forge/platform-auth-node@workspace:*",))

    spec = json.loads(backend_pkg.read_text(encoding="utf-8"))["dependencies"][
        "@forge/platform-auth-node"
    ]
    assert spec == "workspace:*"


def test_unscoped_workspace_dep_also_rewrites(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    backend_pkg = project / "services" / "node-svc" / "package.json"
    (project / "sdks" / "some-pkg").mkdir(parents=True)
    _write_pkg(backend_pkg)

    _add_node_deps(backend_pkg, ("some-pkg@workspace:*",))

    spec = json.loads(backend_pkg.read_text(encoding="utf-8"))["dependencies"]["some-pkg"]
    assert spec == "file:../../sdks/some-pkg"


def test_existing_dep_not_overwritten(tmp_path: Path) -> None:
    """If the dep already has a version pinned, the rewrite must not clobber it."""
    project = tmp_path / "proj"
    backend_pkg = project / "services" / "node-svc" / "package.json"
    (project / "sdks" / "platform-auth-node").mkdir(parents=True)
    backend_pkg.parent.mkdir(parents=True, exist_ok=True)
    backend_pkg.write_text(
        json.dumps(
            {
                "name": "consumer",
                "version": "0.0.0",
                "dependencies": {"@forge/platform-auth-node": "1.2.3"},
            }
        ),
        encoding="utf-8",
    )

    _add_node_deps(backend_pkg, ("@forge/platform-auth-node@workspace:*",))

    spec = json.loads(backend_pkg.read_text(encoding="utf-8"))["dependencies"][
        "@forge/platform-auth-node"
    ]
    assert spec == "1.2.3", "user-pinned version should win over workspace:* rewrite"


def test_non_workspace_specs_unchanged(tmp_path: Path) -> None:
    """Regular ``name@1.2.3`` specs go through the existing path unchanged."""
    project = tmp_path / "proj"
    backend_pkg = project / "services" / "node-svc" / "package.json"
    _write_pkg(backend_pkg)

    _add_node_deps(backend_pkg, ("fastify@5.0.0", "ky@1.8.1"))

    deps = json.loads(backend_pkg.read_text(encoding="utf-8"))["dependencies"]
    assert deps == {"fastify": "5.0.0", "ky": "1.8.1"}
