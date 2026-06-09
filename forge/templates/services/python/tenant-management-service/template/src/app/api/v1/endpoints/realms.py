# src/app/api/v1/endpoints/realms.py
"""REST endpoints for realm management."""

from __future__ import annotations

from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.errors import AlreadyExistsError, ApplicationError, NotFoundError
from app.domain.realm import PaginatedRealmResponse, Realm, RealmCreate, RealmType, RealmUpdate
from app.services.realm_service import RealmService
from forge_core.security.auth import oauth2_scheme

router = APIRouter(route_class=DishkaRoute, dependencies=[Depends(oauth2_scheme)])


@router.get(
    "",
    response_model=PaginatedRealmResponse,
    status_code=status.HTTP_200_OK,
    summary="List realms",
    operation_id="listRealms",
)
async def list_realms(
    service: FromDishka[RealmService],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    realm_type: RealmType | None = Query(None, alias="type"),  # noqa: B008
) -> PaginatedRealmResponse:
    return await service.list(skip=skip, limit=limit, realm_type=realm_type)


@router.post(
    "",
    response_model=Realm,
    status_code=status.HTTP_201_CREATED,
    summary="Create realm",
    operation_id="createRealm",
)
async def create_realm(
    service: FromDishka[RealmService],
    data: RealmCreate,
) -> Realm:
    try:
        return await service.create(data)
    except AlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "/{realm_id}",
    response_model=Realm,
    status_code=status.HTTP_200_OK,
    summary="Get realm",
    operation_id="getRealm",
)
async def get_realm(
    realm_id: UUID,
    service: FromDishka[RealmService],
) -> Realm:
    try:
        return await service.get(realm_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch(
    "/{realm_id}",
    response_model=Realm,
    status_code=status.HTTP_200_OK,
    summary="Update realm",
    operation_id="updateRealm",
)
async def update_realm(
    realm_id: UUID,
    service: FromDishka[RealmService],
    data: RealmUpdate,
) -> Realm:
    try:
        return await service.update(realm_id, data)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete(
    "/{realm_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete realm",
    operation_id="deleteRealm",
)
async def delete_realm(
    realm_id: UUID,
    service: FromDishka[RealmService],
) -> None:
    try:
        await service.delete(realm_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ApplicationError as exc:
        # Realm still has active tenants — a conflict, not a server error.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
