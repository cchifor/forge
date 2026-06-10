"""WS-5.5: the generated chat client must send credentials when auth is on.

The generated app authenticates via a BFF session cookie (the proxy injects
the bearer token server-side; ``useAuth.getToken()`` returns null in that
posture). The main API client already sends ``credentials: 'include'``, but
the AG-UI chat client's POST did not — so a booted chat turn 401'd in every
auth-enabled deployment. These run in generated projects (no TS toolchain in
the forge venv), so we assert on the vendored template source.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_CLIENTS = [
    _ROOT
    / "forge/templates/apps/vue-frontend-template/template"
    / "src/features/ai_chat/canvas-core/ag_ui_client.ts",
    _ROOT
    / "forge/templates/apps/svelte-frontend-template/template"
    / "src/lib/features/chat/canvas-core/ag_ui_client.ts",
]


@pytest.mark.parametrize("path", _CLIENTS, ids=lambda p: p.parent.parent.name)
def test_ag_ui_client_sends_credentials(path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    # The fetch must pass a credentials mode...
    assert "credentials: this.options.credentials" in src, (
        f"{path.name} POST must send the BFF session cookie via credentials"
    )
    # ...defaulting to 'include' so cookies flow without explicit config.
    assert "options.credentials ?? 'include'" in src, (
        f"{path.name} must default credentials to 'include'"
    )


def test_both_clients_identical() -> None:
    # The vue + svelte vendored copies must stay byte-identical (they are
    # maintained by manual discipline today; this catches drift like a
    # credentials fix landing in only one).
    bodies = [p.read_text(encoding="utf-8") for p in _CLIENTS]
    assert bodies[0] == bodies[1], (
        "vue and svelte vendored ag_ui_client.ts have drifted"
    )
