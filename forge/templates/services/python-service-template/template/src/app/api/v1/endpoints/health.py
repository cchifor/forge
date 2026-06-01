from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Response, status

from app.core.ioc import PublicUnitOfWork
from app.domain.health import HealthStatus, LivenessResponse, ReadinessResponse
from app.services.health_service import HealthService

router = APIRouter()


@router.get("/live", response_model=LivenessResponse)
@inject
async def liveness_probe(service: FromDishka[HealthService]):
    return await service.check_liveness()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={
        503: {
            "model": ReadinessResponse,
            "description": "Service dependencies unavailable",
        }
    },
)
@inject
async def readiness_probe(
    response: Response,
    uow: FromDishka[PublicUnitOfWork],
    service: FromDishka[HealthService],
):
    try:
        async with uow:
            health_data = await service.check_readiness(uow)
    except Exception:
        # A failing dependency check (e.g. DB unreachable) means NOT ready:
        # return 503 so orchestrators stop routing traffic, rather than letting
        # the exception surface as a 500 (which a liveness-style reading would
        # treat as "alive but erroring").
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status=HealthStatus.DOWN, components={})
    if health_data.status != HealthStatus.UP:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return health_data
