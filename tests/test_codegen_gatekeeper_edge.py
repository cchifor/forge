"""Regression: codegen + gatekeeper edge cases (audit #10, #26, #28)."""

from __future__ import annotations

from pathlib import Path

from forge.injectors.ts_ast import inject_ts

_GK = (
    Path(__file__).resolve().parent.parent
    / "forge/features/auth/templates/platform_auth_gatekeeper/all/files/deploy/infra/gatekeeper/src/app/gatekeeper"
)


# --- #26: ts_ast must not fuse the BEGIN sentinel onto an EOF anchor ----------
def test_ts_anchor_on_last_line_no_trailing_newline_does_not_fuse(tmp_path: Path) -> None:
    src = tmp_path / "app.ts"
    # Anchor on the file's last line, NO trailing newline.
    src.write_text("const app = 1;\n// FORGE:X", encoding="utf-8")
    inject_ts(src, "f", "X", "const x = 1;", "after")
    out = src.read_text(encoding="utf-8")
    # The BEGIN sentinel must start on its own line (not fused onto the anchor).
    assert "\n// FORGE:BEGIN f:X" in out
    assert "// FORGE:X//" not in out  # anchor not fused with the sentinel
    # Re-run stays idempotent — exactly one block, anchor preserved.
    inject_ts(src, "f", "X", "const x = 1;", "after")
    out2 = src.read_text(encoding="utf-8")
    assert out2.count("FORGE:BEGIN f:X") == 1


# --- #10: single-use OAuth token ops must not be retried ----------------------
def test_oauth_token_exchange_not_retried() -> None:
    oidc = (_GK / "oidc.py").read_text(encoding="utf-8")
    # exchange_code + refresh_tokens are non-idempotent; @with_retry would replay
    # a single-use code / rotated refresh token after a read-timeout.
    assert "@with_retry()" not in oidc
    assert "import with_retry" not in oidc and ", with_retry" not in oidc


# --- #28: gatekeeper /callback reject branches must not NameError -------------
def test_routes_imports_session_fp() -> None:
    routes = (_GK / "routes.py").read_text(encoding="utf-8")
    # _pop_auth_state logs session_fp(state) on its reject branches.
    assert "import session_fp" in routes
