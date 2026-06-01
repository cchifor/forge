"""Admin endpoints for runtime diagnostics.

WS-2.9 — these mutate process state without authentication, so they are
**not** reachable in production. ``require_non_production`` gates every route
on this router behind the active environment: when ``ENV`` resolves to a
production-class value the route returns ``404`` (hidden), otherwise it is
served for local/dev diagnostics. Deployments that want runtime log-level
overrides in prod must put the route behind the platform admin scope instead
of relying on the open endpoint.
"""

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

# Environment names that must never expose the unauthenticated admin surface.
_PRODUCTION_ENVS = {"production", "prod", "staging"}


def require_non_production() -> None:
    """Dependency: reject admin diagnostics when running in production.

    The active environment is sourced from ``ENV`` (the same knob the config
    loader's ``_active_env`` reads, and the value the Dockerfile bakes in as
    ``ENV=production``). In a production-class environment the route is hidden
    behind a ``404`` so the open log-level override can't be abused.
    """
    active_env = os.environ.get("ENV", "development").strip().lower()
    if active_env in _PRODUCTION_ENVS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not Found",
        )


router = APIRouter(dependencies=[Depends(require_non_production)])


class LogLevelRequest(BaseModel):
    logger: str = Field("root", description="Logger name (e.g. 'app', 'api.access', 'root')")
    level: str = Field(..., description="DEBUG, INFO, WARNING, ERROR, CRITICAL")


class LogLevelResponse(BaseModel):
    logger: str
    previous_level: str
    current_level: str


@router.post(
    "/log-level",
    response_model=LogLevelResponse,
    summary="Override log level at runtime",
    description="Temporarily change the log level for a specific logger without restarting.",
)
async def set_log_level(request: LogLevelRequest) -> LogLevelResponse:
    target = logging.getLogger(request.logger if request.logger != "root" else None)
    previous = logging.getLevelName(target.level)

    numeric_level = getattr(logging, request.level.upper(), None)
    if numeric_level is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid log level: {request.level}",
        )

    target.setLevel(numeric_level)
    return LogLevelResponse(
        logger=request.logger,
        previous_level=previous,
        current_level=request.level.upper(),
    )
