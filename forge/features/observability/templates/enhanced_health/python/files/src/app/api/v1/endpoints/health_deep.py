"""Deep readiness endpoint that pings downstream services.

GET /api/v1/health/deep aggregates check_redis + check_keycloak alongside
the primary database check already performed by the base health router.
Returns 503 if any downstream component is DOWN so orchestrators (k8s,
Docker healthcheck) can react.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.core.health_checks import check_keycloak, check_redis

router = APIRouter()


@router.get("/deep")
async def deep_readiness(response: Response) -> dict:
    redis = await check_redis()
    keycloak = await check_keycloak()
    components = {
        "redis": redis.as_dict(),
        "keycloak": keycloak.as_dict(),
    }
    overall_up = redis.up and keycloak.up
    if not overall_up:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "up" if overall_up else "down",
        "components": components,
    }
