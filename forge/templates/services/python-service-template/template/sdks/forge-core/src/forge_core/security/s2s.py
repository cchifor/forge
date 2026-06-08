"""Service-to-service (S2S) authorization dependency for FastAPI endpoints.

Hardens internal endpoints that exist to serve traffic from *other services*
(not the SPA, not end-user agents). ``AuthGuard`` verifies the bearer token but
does not enforce *who* the caller is; for an internal surface returning
tenant-scoped data, "any verified caller" is too permissive — we want to assert
the caller is one of a known allow-list of services.

The gatekeeper's S2S token mint carries three claims that make this decision
possible (claim names are configurable, defaulting to the gatekeeper's):

* ``azp`` — the client_id of the calling service (e.g. ``svc-orders``).
* ``platform_target_service`` — the downstream service the token was minted
  *for*; pinning it stops a token minted for one service being replayed
  against another.
* ``scope`` — the per-service scopes granted at mint time.

:func:`require_service` builds a FastAPI dependency enforcing all three::

    @router.get(
        "/internal/derived-records",
        dependencies=[Depends(require_service(
            target_service="svc-orders",
            allowed_callers=("svc-catalog",),
            required_scope="orders:read",
        ))],
    )

Failures: 401 (no verified identity), 403 ``forbidden_caller`` (azp not allowed
/ missing), 403 ``audience_mismatch`` (token minted for a different downstream),
403 ``scope_required`` (scope not satisfied). It reads the verified identity
from ``request.state.identity`` (populated by the auth middleware) and does not
re-run signature/issuer verification — that happened upstream.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from fastapi import HTTPException, Request, status

from forge_core.security.identity import IdentityContext
from forge_core.security.scopes import scope_satisfies

__all__ = ["require_service"]


def require_service(
    *,
    target_service: str,
    allowed_callers: Iterable[str],
    required_scope: str | None = None,
    target_service_claim: str = "platform_target_service",
    caller_claim: str = "azp",
) -> Callable[[Request], Awaitable[IdentityContext]]:
    """Build a FastAPI dependency that enforces S2S authorization.

    Parameters
    ----------
    target_service:
        Expected value of the token's target-service claim — usually this
        service's own client_id. Pinning it prevents a token minted for one
        downstream from being replayed against another.
    allowed_callers:
        Allow-list of caller client_ids (the ``caller_claim`` value). Any other
        caller is rejected 403. A missing/empty caller claim is always rejected
        — only service-account tokens carry it, so an absent value almost
        certainly means an end-user token leaked onto an S2S route.
    required_scope:
        Optional scope the caller must satisfy (wildcard-aware via
        :func:`scope_satisfies`). ``None`` skips the scope check.
    target_service_claim / caller_claim:
        Claim names to read, defaulting to the gatekeeper's
        ``platform_target_service`` / ``azp``. Override for a different issuer.

    Returns the verified :class:`IdentityContext` on success.
    """
    if isinstance(allowed_callers, str):
        # A bare string would frozenset() into a set of characters and reject
        # every caller — almost certainly a typo for a 1-tuple.
        raise ValueError("allowed_callers must be a collection of client_ids, not a single string")
    allowed_set = frozenset(allowed_callers)
    if not allowed_set:
        # An empty allow-list would let any verified caller through — almost
        # certainly a wiring bug; fail loudly at build time.
        raise ValueError("allowed_callers must contain at least one entry")
    if not target_service:
        raise ValueError("target_service must be non-empty")

    async def dependency(request: Request) -> IdentityContext:
        identity: IdentityContext | None = getattr(request.state, "identity", None)
        if identity is None:
            auth_error = getattr(request.state, "auth_error", None)
            detail: dict[str, Any] = {"reason": "not_authenticated"}
            if isinstance(auth_error, dict):
                detail.update(auth_error)
            elif auth_error is not None:
                detail["detail"] = str(auth_error)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=detail,
                headers={"WWW-Authenticate": "Bearer"},
            )

        claims = identity.raw_claims
        caller = claims.get(caller_claim)
        if not isinstance(caller, str) or not caller:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "reason": "forbidden_caller",
                    "detail": f"token is missing service identity ({caller_claim})",
                },
            )
        if caller not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "reason": "forbidden_caller",
                    "detail": f"caller {caller!r} is not authorized for this endpoint",
                },
            )

        token_target = claims.get(target_service_claim)
        if not isinstance(token_target, str) or token_target != target_service:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "reason": "audience_mismatch",
                    "detail": (
                        f"token was minted for {token_target!r}, not {target_service!r}"
                    ),
                },
            )

        if required_scope is not None and not scope_satisfies(required_scope, identity.scopes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "reason": "scope_required",
                    "detail": f"required scope {required_scope!r} not present",
                    "missing_scopes": [required_scope],
                },
            )

        return identity

    return dependency
