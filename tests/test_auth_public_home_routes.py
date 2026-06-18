"""Regression: generated home routes are public in Node + Rust (audit #23).

The Node ``app.ts`` mounts ``homeRoutes`` under prefix ``/api/v1`` and the Rust
router merges ``home::routes()`` (``/`` + ``/info``) inside the ``/api/v1`` nest,
so the live service-info paths are ``/api/v1/`` and ``/api/v1/info``. Both
templates document these as public, unauthenticated endpoints — but the Node
``DEFAULT_EXCLUDED_PATHS`` and Rust ``EXCLUDED_PATHS`` skip-lists omitted them.

Node/Rust enforce auth via a GLOBAL hard-reject middleware (onRequest hook /
``from_fn`` layer) that 401s any token-less path not on the skip-list, whereas
Python soft-passes token-less requests and gates per-route via
``Depends(get_current_user)`` (home has no dependency + is in the Python public
allowlist). So with auth enabled the Node/Rust home/info endpoints 401'd while
Python served them 200 — a broken doc promise + cross-language inconsistency.

This pins both skip-lists to the public home paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_AUTH = Path(__file__).resolve().parent.parent / "forge" / "features" / "auth" / "templates"
_NODE_PLUGIN = (
    _AUTH
    / "platform_auth_sdk_node/node/files/packages/platform-auth-node/src/plugin.ts"
)
_RUST_AUTH = (
    _AUTH / "platform_auth_rust_middleware/rust/files/src/middleware/auth.rs"
)

# Live paths of the generated welcome (`/`) and service-info (`/info`) routes,
# both mounted under the `/api/v1` prefix/nest.
_PUBLIC_HOME_PATHS = ("/api/v1/", "/api/v1/info")


@pytest.mark.parametrize("path", _PUBLIC_HOME_PATHS)
def test_node_skiplist_includes_public_home(path: str) -> None:
    src = _NODE_PLUGIN.read_text(encoding="utf-8")
    assert f'"{path}"' in src, (
        f"Node DEFAULT_EXCLUDED_PATHS is missing public home path {path!r}; "
        "auth-on Node backends 401 their documented-public service-info endpoint"
    )


@pytest.mark.parametrize("path", _PUBLIC_HOME_PATHS)
def test_rust_skiplist_includes_public_home(path: str) -> None:
    src = _RUST_AUTH.read_text(encoding="utf-8")
    assert f'"{path}"' in src, (
        f"Rust EXCLUDED_PATHS is missing public home path {path!r}; "
        "auth-on Rust backends 401 their documented-public service-info endpoint"
    )
