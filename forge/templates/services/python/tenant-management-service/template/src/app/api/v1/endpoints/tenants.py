# src/app/api/v1/endpoints/tenants.py
"""REST endpoints for tenant management and provisioning."""

from __future__ import annotations

from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.errors import AlreadyExistsError, NotFoundError
from app.domain.tenant import (
    PaginatedTenantResponse,
    Tenant,
    TenantProvisionRequest,
    TenantStatus,
    TenantTier,
)
from app.services.tenant_service import TenantService
from forge_core.errors import ApplicationError
from forge_core.security.auth import oauth2_scheme

router = APIRouter(route_class=DishkaRoute, dependencies=[Depends(oauth2_scheme)])


@router.post(
    "/provision",
    response_model=Tenant,
    status_code=status.HTTP_201_CREATED,
    summary="Provision a new tenant (full workflow)",
    operation_id="provisionTenant",
)
async def provision_tenant(
    service: FromDishka[TenantService],
    data: TenantProvisionRequest,
) -> Tenant:
    try:
        return await service.provision(data)
    except AlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ApplicationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.get(
    "",
    response_model=PaginatedTenantResponse,
    status_code=status.HTTP_200_OK,
    summary="List tenants",
    operation_id="listTenants",
)
async def list_tenants(
    service: FromDishka[TenantService],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    tenant_status: TenantStatus | None = Query(None, alias="status"),  # noqa: B008
    tier: TenantTier | None = Query(None),  # noqa: B008
    realm_id: UUID | None = Query(None),  # noqa: B008
) -> PaginatedTenantResponse:
    return await service.list(
        skip=skip,
        limit=limit,
        status=tenant_status,
        tier=tier,
        realm_id=realm_id,
    )


@router.get(
    "/by-slug/{slug}",
    response_model=Tenant,
    status_code=status.HTTP_200_OK,
    summary="Get tenant by slug",
    operation_id="getTenantBySlug",
)
async def get_tenant_by_slug(
    slug: str,
    service: FromDishka[TenantService],
) -> Tenant:
    try:
        return await service.get_by_slug(slug)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/{tenant_id}",
    response_model=Tenant,
    status_code=status.HTTP_200_OK,
    summary="Get tenant by ID",
    operation_id="getTenant",
)
async def get_tenant(
    tenant_id: UUID,
    service: FromDishka[TenantService],
) -> Tenant:
    try:
        return await service.get(tenant_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/{tenant_id}/suspend",
    response_model=Tenant,
    status_code=status.HTTP_200_OK,
    summary="Suspend tenant",
    operation_id="suspendTenant",
)
async def suspend_tenant(
    tenant_id: UUID,
    service: FromDishka[TenantService],
) -> Tenant:
    try:
        return await service.suspend(tenant_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ApplicationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.post(
    "/{tenant_id}/reactivate",
    response_model=Tenant,
    status_code=status.HTTP_200_OK,
    summary="Reactivate tenant",
    operation_id="reactivateTenant",
)
async def reactivate_tenant(
    tenant_id: UUID,
    service: FromDishka[TenantService],
) -> Tenant:
    try:
        return await service.reactivate(tenant_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ApplicationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.post(
    "/sync-redis",
    status_code=status.HTTP_200_OK,
    summary="Re-publish all active tenant routes to Redis",
    operation_id="syncRedis",
)
async def sync_redis(
    service: FromDishka[TenantService],
) -> dict[str, int]:
    count = await service.sync_all_to_redis()
    return {"synced": count}
