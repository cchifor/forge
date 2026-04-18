"""Fragment smoke tests for `webhooks`.

Covers the A1.5 nonce-in-signature invariant: different nonces must
yield different signatures, and the HMAC is deterministic for a given
input tuple.
"""

from __future__ import annotations

import hmac
import hashlib

from app.services.webhook_service import _sign, generate_secret, matches_event
from app.data.models.webhook import Webhook


def test_sign_is_deterministic() -> None:
    secret = "topsecret"
    body = b'{"k": "v"}'
    sig1 = _sign(secret, body, "1700000000", "abcdef0123456789abcdef0123456789")
    sig2 = _sign(secret, body, "1700000000", "abcdef0123456789abcdef0123456789")
    assert sig1 == sig2


def test_different_nonce_different_signature() -> None:
    secret = "topsecret"
    body = b'{"k": "v"}'
    a = _sign(secret, body, "1700000000", "a" * 32)
    b = _sign(secret, body, "1700000000", "b" * 32)
    assert a != b, "nonce must affect the HMAC so within-second replays are rejected"


def test_different_timestamp_different_signature() -> None:
    secret = "topsecret"
    body = b'{"k": "v"}'
    a = _sign(secret, body, "1700000000", "a" * 32)
    b = _sign(secret, body, "1700000001", "a" * 32)
    assert a != b


def test_signature_matches_reference_hmac() -> None:
    secret = "topsecret"
    body = b'{"k": "v"}'
    ts = "1700000000"
    nonce = "z" * 32
    expected_msg = ts.encode() + b"." + nonce.encode() + b"." + body
    expected = hmac.new(secret.encode(), expected_msg, hashlib.sha256).hexdigest()
    assert _sign(secret, body, ts, nonce) == expected


def test_generate_secret_is_64_hex_chars() -> None:
    s = generate_secret()
    assert len(s) == 64
    assert all(c in "0123456789abcdef" for c in s)


def test_matches_event_empty_subscribes_all() -> None:
    wh = Webhook(id=None, name="w", url="http://x", secret="s", events=[], is_active=True)  # type: ignore[call-arg]
    assert matches_event(wh, "anything.happens") is True


def test_matches_event_glob() -> None:
    wh = Webhook(id=None, name="w", url="http://x", secret="s", events=["user.*"], is_active=True)  # type: ignore[call-arg]
    assert matches_event(wh, "user.created") is True
    assert matches_event(wh, "order.created") is False
