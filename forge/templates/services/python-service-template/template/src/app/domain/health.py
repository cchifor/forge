import platform
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class HealthStatus(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    DEGRADED = "DEGRADED"


class ComponentStatus(BaseModel):
    status: HealthStatus
    latency_ms: float | None = Field(None, description="Latency in milliseconds")
    details: dict[str, Any] | None = None


class ReadinessResponse(BaseModel):
    status: HealthStatus
    components: dict[str, ComponentStatus]
    system_info: dict[str, str] = Field(
        default_factory=lambda: {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        }
    )


class LivenessResponse(BaseModel):
    status: HealthStatus = HealthStatus.UP
    details: str = "Service is running"
