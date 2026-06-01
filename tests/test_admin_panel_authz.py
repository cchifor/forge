"""WS-2.8: the generated admin panel must gate /admin behind an admin role.

The SQLAdmin panel (``forge/features/platform/templates/admin_panel/python/
.../admin.py``) historically mounted ``Admin(app, engine)`` with NO
``authentication_backend`` — anyone who reached the route (or spoofed a
gateway header) got in. It also read ``ENVIRONMENT`` only, diverging from
the gatekeeper's ``ENV``-first convention.

This template runs in generated projects, not the forge venv, so we assert
on the template source (the established idiom for template files).
"""

from __future__ import annotations

from pathlib import Path

_ADMIN_PY = (
    Path(__file__).resolve().parent.parent
    / "forge"
    / "features"
    / "platform"
    / "templates"
    / "admin_panel"
    / "python"
    / "files"
    / "src"
    / "app"
    / "admin.py"
)


def _src() -> str:
    return _ADMIN_PY.read_text(encoding="utf-8")


def test_defines_authentication_backend() -> None:
    src = _src()
    assert "AuthenticationBackend" in src, (
        "admin panel must define an SQLAdmin AuthenticationBackend subclass"
    )
    assert "async def authenticate" in src, "the backend must implement authenticate()"


def test_admin_mounted_with_authentication_backend() -> None:
    src = _src()
    # The Admin() construction must pass authentication_backend=, not mount bare.
    assert "authentication_backend=" in src, (
        "Admin(...) must be constructed with authentication_backend=<backend>"
    )


def test_authenticate_checks_admin_role_from_forwarded_header() -> None:
    src = _src()
    # The gateway forwards roles as the comma-separated X-Gatekeeper-Roles header.
    assert "X-Gatekeeper-Roles" in src or "x-gatekeeper-roles" in src, (
        "admin authz must consult the forwarded X-Gatekeeper-Roles header"
    )
    # An admin-role gate must exist (env-configurable, default 'admin').
    assert "ADMIN_ROLE" in src or "admin_role" in src, (
        "admin authz must check an admin role (configurable via ADMIN_ROLE)"
    )


def test_env_resolution_prefers_ENV_then_ENVIRONMENT() -> None:
    src = _src()
    # Standardize on ENV first, fall back to ENVIRONMENT (gatekeeper parity).
    assert 'os.environ.get("ENV"' in src, "env resolution must try ENV first"
    assert "ENVIRONMENT" in src, "env resolution must still fall back to ENVIRONMENT"
