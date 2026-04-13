import time

from app.domain.health import (
    ComponentStatus,
    HealthStatus,
    LivenessResponse,
    ReadinessResponse,
)
from service.uow.aio import AsyncUnitOfWork, HealthRepository


class HealthService:
    async def check_liveness(self) -> LivenessResponse:
        return LivenessResponse(status=HealthStatus.UP, details="Service is running")

    async def check_readiness(self, uow: AsyncUnitOfWork) -> ReadinessResponse:
        components: dict[str, ComponentStatus] = {}

        # Database check
        start = time.perf_counter()
        repo = uow.repo(HealthRepository)
        db_ok = await repo.ping_db()
        latency = (time.perf_counter() - start) * 1000

        components["database"] = ComponentStatus(
            status=HealthStatus.UP if db_ok else HealthStatus.DOWN,
            latency_ms=round(latency, 2),
        )

        overall = (
            HealthStatus.UP
            if all(c.status == HealthStatus.UP for c in components.values())
            else HealthStatus.DOWN
        )

        return ReadinessResponse(status=overall, components=components)
