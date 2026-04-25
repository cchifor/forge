"""Assertions over the RFC-007 error envelope.

Every error response from a forge-generated backend follows the
shape ``{"error": {"code", "message", "type", "context",
"correlation_id"}}``. Tests should assert on the structured envelope,
not on free-form message strings — message text is allowed to drift
between releases, codes and status mappings are not.
"""

from __future__ import annotations

from typing import Any


def assert_error_envelope(
    response: Any,
    *,
    code: str,
    status: int,
    message_contains: str | None = None,
    type_name: str | None = None,
    context_subset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assert that ``response`` carries an RFC-007 error envelope.

    ``response`` is anything with ``.status_code`` and a ``.json()``
    accessor (FastAPI's TestClient response, httpx response, etc.).

    Returns the parsed ``error`` body so callers can make additional
    assertions when the contract above isn't sufficient.
    """
    assert response.status_code == status, (
        f"expected status {status}, got {response.status_code}"
    )
    body = response.json()
    assert "error" in body, f"response body missing 'error' envelope: {body}"
    err = body["error"]
    assert err["code"] == code, f"expected code {code!r}, got {err.get('code')!r}"
    assert "correlation_id" in err, "envelope missing correlation_id"
    assert "context" in err, "envelope missing context"
    if message_contains is not None:
        assert message_contains in err["message"], (
            f"expected {message_contains!r} in message, got {err['message']!r}"
        )
    if type_name is not None:
        assert err["type"] == type_name, (
            f"expected type {type_name!r}, got {err.get('type')!r}"
        )
    if context_subset is not None:
        for key, value in context_subset.items():
            assert err["context"].get(key) == value, (
                f"context[{key!r}] = {err['context'].get(key)!r}, expected {value!r}"
            )
    return err
