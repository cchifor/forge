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
    async with uow:
        health_data = await service.check_readiness(uow)
    if health_data.status != HealthStatus.UP:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return health_data
