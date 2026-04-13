"""REST endpoints for item management.

Routes
------
GET    /items            -- List items (paginated, filtered)
POST   /items            -- Create a new item
GET    /items/{id}       -- Get item by ID
PATCH  /items/{id}       -- Update an item
DELETE /items/{id}       -- Delete an item
"""

from __future__ import annotations

from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.errors import AlreadyExistsError, NotFoundError
from app.domain.item import (
    Item,
    ItemCreate,
    ItemStatus,
    ItemUpdate,
    PaginatedItemResponse,
)
from app.services.item_service import ItemService
from service.security.auth import oauth2_scheme

router = APIRouter(route_class=DishkaRoute, dependencies=[Depends(oauth2_scheme)])


@router.get(
    "",
    response_model=PaginatedItemResponse,
    status_code=status.HTTP_200_OK,
    summary="List items",
    operation_id="listItems",
)
async def list_items(
    service: FromDishka[ItemService],
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    item_status: ItemStatus | None = Query(None, alias="status", description="Filter by status"),
    search: str | None = Query(
        None, max_length=200, description="Case-insensitive name/description search"
    ),
) -> PaginatedItemResponse:
    return await service.list(skip=skip, limit=limit, status=item_status, search=search)


@router.post(
    "",
    response_model=Item,
    status_code=status.HTTP_201_CREATED,
    summary="Create item",
    operation_id="createItem",
)
async def create_item(
    service: FromDishka[ItemService],
    data: ItemCreate,
) -> Item:
    try:
        return await service.create(data)
    except AlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "/{item_id}",
    response_model=Item,
    status_code=status.HTTP_200_OK,
    summary="Get item",
    operation_id="getItem",
)
async def get_item(
    item_id: UUID,
    service: FromDishka[ItemService],
) -> Item:
    try:
        return await service.get(item_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch(
    "/{item_id}",
    response_model=Item,
    status_code=status.HTTP_200_OK,
    summary="Update item",
    operation_id="updateItem",
)
async def update_item(
    item_id: UUID,
    service: FromDishka[ItemService],
    data: ItemUpdate,
) -> Item:
    try:
        return await service.update(item_id, data)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete item",
    operation_id="deleteItem",
)
async def delete_item(
    item_id: UUID,
    service: FromDishka[ItemService],
) -> None:
    try:
        await service.delete(item_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
