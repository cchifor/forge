"""Admin endpoints for runtime diagnostics."""

import logging

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

router = APIRouter()


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
