"""Webhook CRUD + test-fire endpoints.

Auth-gated and tenant-scoped: the router requires an authenticated user
(``Depends(get_current_user)``) and every query runs through the
``AuthUnitOfWork`` (which binds the verified account for DB-layer isolation
when multitenancy is on) AND filters explicitly by the caller's verified
``customer_id`` (defense for non-multitenant projects with no RLS). Webhook
URLs are credentials (they receive your event stream); test-fire makes an
outbound request whose target is validated against the SSRF deny-list in
``webhook_service.deliver``.
"""

from __future__ import annotations

import uuid

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Depends, HTTPException, status
from forge_core.domain.user import User
from forge_core.security.auth import get_current_user
from sqlalchemy import select

from app.core.ioc import AuthUnitOfWork
from app.data.models.webhook import Webhook as WebhookModel
from app.domain.webhook import Webhook, WebhookCreate, WebhookDeliveryResult
from app.services.webhook_service import (
    WebhookUrlError,
    deliver,
    generate_secret,
    validate_outbound_url,
)

# Webhook CRUD + test-fire must be authenticated: test-fire performs an
# outbound request to a caller-controlled URL (SSRF surface, mitigated in
# webhook_service.deliver), and the rows are tenant-owned credentials.
router = APIRouter(dependencies=[Depends(get_current_user)])


def _tenant_id(user: User) -> uuid.UUID:
    """The caller's verified tenant id, from the validated token's tenant
    claim — never request-supplied. Fails closed on a non-UUID tenant."""
    try:
        return uuid.UUID(str(user.customer_id))
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="no tenant context",
        ) from e


def _user_id(user: User) -> uuid.UUID:
    try:
        return uuid.UUID(str(user.id))
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="no user context",
        ) from e


@router.get("", response_model=list[Webhook])
@inject
async def list_webhooks(
    uow: FromDishka[AuthUnitOfWork],
    user: User = Depends(get_current_user),
) -> list[Webhook]:
    cid = _tenant_id(user)
    async with uow:
        stmt = (
            select(WebhookModel)
            .where(WebhookModel.customer_id == cid)
            .order_by(WebhookModel.created_at.desc())
            .limit(200)
        )
        result = await uow.session.execute(stmt)
        return [Webhook.model_validate(row) for row in result.scalars().all()]


@router.post("", response_model=Webhook, status_code=status.HTTP_201_CREATED)
@inject
async def create_webhook(
    uow: FromDishka[AuthUnitOfWork],
    data: WebhookCreate,
    user: User = Depends(get_current_user),
) -> Webhook:
    # Reject internal/non-public targets up front (fast feedback); deliver()
    # re-checks at fire time since DNS can change.
    try:
        validate_outbound_url(str(data.url))
    except WebhookUrlError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    async with uow:
        model = WebhookModel(
            id=uuid.uuid4(),
            name=data.name,
            url=str(data.url),
            secret=generate_secret(),
            events=list(data.events),
            extra_headers=data.extra_headers,
            customer_id=_tenant_id(user),
            user_id=_user_id(user),
            is_active=True,
        )
        uow.session.add(model)
        await uow.session.flush()
        await uow.commit()
        return Webhook.model_validate(model)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_webhook(
    webhook_id: uuid.UUID,
    uow: FromDishka[AuthUnitOfWork],
    user: User = Depends(get_current_user),
) -> None:
    cid = _tenant_id(user)
    async with uow:
        stmt = select(WebhookModel).where(
            WebhookModel.id == webhook_id,
            WebhookModel.customer_id == cid,
        )
        result = await uow.session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        await uow.session.delete(model)
        await uow.commit()


@router.post("/{webhook_id}/test", response_model=WebhookDeliveryResult)
@inject
async def test_webhook(
    webhook_id: uuid.UUID,
    uow: FromDishka[AuthUnitOfWork],
    user: User = Depends(get_current_user),
) -> WebhookDeliveryResult:
    """Fire a canned `webhook.test` event at the registered URL."""
    cid = _tenant_id(user)
    async with uow:
        stmt = select(WebhookModel).where(
            WebhookModel.id == webhook_id,
            WebhookModel.customer_id == cid,
        )
        result = await uow.session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return await deliver(
        model,
        event="webhook.test",
        payload={"message": "forge webhook test"},
    )
