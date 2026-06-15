"""Behavioural tests for the Gatekeeper OIDC PKCE + nonce pure helpers (WS-2.5).

These exercise the stdlib-only crypto helpers that the generated Gatekeeper
ships at ``src/app/gatekeeper/oidc_pkce.py``. The module is deliberately
dependency-free (no fastapi / redis / PyJWT) so it can be importlib-loaded
straight from the template path inside forge's CI — exactly like
``tests/test_mcp_audit.py`` loads the MCP audit middleware.

The S256 reference vector is RFC 7636 Appendix B:
    code_verifier  = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    code_challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_pkce_module():
    path = (
        Path(__file__).resolve().parent.parent
        / "forge"
        / "features"
        / "auth"
        / "templates"
        / "platform_auth_gatekeeper"
        / "all"
        / "files"
        / "deploy"
        / "infra"
        / "gatekeeper"
        / "src"
        / "app"
        / "gatekeeper"
        / "oidc_pkce.py"
    )
    spec = importlib.util.spec_from_file_location("gk_oidc_pkce_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["gk_oidc_pkce_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def pkce():
    return _load_pkce_module()


# RFC 7636 Appendix B test vector.
RFC7636_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
RFC7636_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"

# The unreserved character set permitted in a PKCE code_verifier (RFC 7636 §4.1).
_UNRESERVED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


class TestS256Challenge:
    def test_rfc7636_reference_vector(self, pkce) -> None:
        """The canonical RFC 7636 Appendix-B verifier→challenge mapping."""
        assert pkce.pkce_challenge_s256(RFC7636_VERIFIER) == RFC7636_CHALLENGE

    def test_challenge_has_no_padding(self, pkce) -> None:
        challenge = pkce.pkce_challenge_s256("some-verifier-value-xxxxxxxxxxxxxxxxxxxxxxx")
        assert "=" not in challenge

    def test_challenge_is_url_safe(self, pkce) -> None:
        challenge = pkce.pkce_challenge_s256(RFC7636_VERIFIER)
        # base64url alphabet only — no '+' or '/'.
        assert "+" not in challenge and "/" not in challenge

    def test_challenge_deterministic(self, pkce) -> None:
        a = pkce.pkce_challenge_s256(RFC7636_VERIFIER)
        b = pkce.pkce_challenge_s256(RFC7636_VERIFIER)
        assert a == b


class TestVerifierGeneration:
    def test_length_within_rfc_bounds(self, pkce) -> None:
        for _ in range(50):
            v = pkce.generate_pkce_verifier()
            assert 43 <= len(v) <= 128, f"verifier length {len(v)} out of [43,128]"

    def test_charset_is_unreserved(self, pkce) -> None:
        for _ in range(50):
            v = pkce.generate_pkce_verifier()
            illegal = set(v) - _UNRESERVED
            assert not illegal, f"verifier contains non-unreserved chars: {illegal}"

    def test_no_padding(self, pkce) -> None:
        assert "=" not in pkce.generate_pkce_verifier()

    def test_distinct_across_calls(self, pkce) -> None:
        seen = {pkce.generate_pkce_verifier() for _ in range(100)}
        assert len(seen) == 100, "verifiers must be unique per call"

    def test_generated_verifier_roundtrips_through_s256(self, pkce) -> None:
        v = pkce.generate_pkce_verifier()
        ch = pkce.pkce_challenge_s256(v)
        assert ch and "=" not in ch


class TestStateAndNonce:
    def test_state_high_entropy(self, pkce) -> None:
        # token_urlsafe(32) yields >= 43 chars.
        assert len(pkce.generate_state()) >= 32

    def test_nonce_high_entropy(self, pkce) -> None:
        assert len(pkce.generate_nonce()) >= 32

    def test_state_distinct_across_calls(self, pkce) -> None:
        seen = {pkce.generate_state() for _ in range(100)}
        assert len(seen) == 100

    def test_nonce_distinct_across_calls(self, pkce) -> None:
        seen = {pkce.generate_nonce() for _ in range(100)}
        assert len(seen) == 100

    def test_state_and_nonce_url_safe(self, pkce) -> None:
        for fn in (pkce.generate_state, pkce.generate_nonce):
            val = fn()
            assert set(val) <= _UNRESERVED, f"{fn.__name__} produced non-url-safe value"


class TestNonceEquality:
    def test_equal_nonces(self, pkce) -> None:
        assert pkce.nonces_equal("abc123", "abc123") is True

    def test_different_nonces(self, pkce) -> None:
        assert pkce.nonces_equal("abc123", "abc124") is False

    def test_empty_vs_value(self, pkce) -> None:
        assert pkce.nonces_equal("", "x") is False

    def test_none_safe(self, pkce) -> None:
        # A None on either side must never compare equal — fail closed.
        assert pkce.nonces_equal(None, "x") is False
        assert pkce.nonces_equal("x", None) is False
        assert pkce.nonces_equal(None, None) is False

    def test_both_empty_now_fail_closed(self, pkce) -> None:
        # WS-2.5 fix (F4): two empty strings must NOT compare equal, so an
        # absent expected-nonce can never spuriously match an absent actual.
        assert pkce.nonces_equal("", "") is False


# ── WS-2.5 review fixes: fail-closed envelope extractors (F3 + F4) ───────────


class TestEnvelopeCodeVerifier:
    def test_returns_value(self, pkce) -> None:
        assert pkce.envelope_code_verifier({"code_verifier": "abc123"}) == "abc123"

    @pytest.mark.parametrize(
        "env",
        [{}, {"code_verifier": ""}, {"code_verifier": None}, {"code_verifier": 123}],
    )
    def test_fails_closed(self, pkce, env) -> None:
        with pytest.raises(ValueError):
            pkce.envelope_code_verifier(env)


class TestEnvelopeNonce:
    def test_returns_value(self, pkce) -> None:
        assert pkce.envelope_nonce({"nonce": "n0nce"}) == "n0nce"

    @pytest.mark.parametrize(
        "env",
        [{}, {"nonce": ""}, {"nonce": None}, {"nonce": 0}],
    )
    def test_fails_closed(self, pkce, env) -> None:
        with pytest.raises(ValueError):
            pkce.envelope_nonce(env)
