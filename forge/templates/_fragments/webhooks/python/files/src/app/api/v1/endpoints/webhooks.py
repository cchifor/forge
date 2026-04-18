"""Webhook CRUD + test-fire endpoints.

Not auth-gated by default. Wrap the router with your auth dependency
before production exposure — webhook URLs are credentials (they receive
your event stream).
"""

from __future__ import annotations

import uuid

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.ioc import PublicUnitOfWork
from app.data.models.webhook import Webhook as WebhookModel
from app.domain.webhook import Webhook, WebhookCreate, WebhookDeliveryResult
from app.services.webhook_service import deliver, generate_secret

router = APIRouter()

_ANON = uuid.UUID("00000000-0000-0000-0000-000000000000")


@router.get("", response_model=list[Webhook])
@inject
async def list_webhooks(uow: FromDishka[PublicUnitOfWork]) -> list[Webhook]:
    async with uow:
        stmt = select(WebhookModel).order_by(WebhookModel.created_at.desc()).limit(200)
        result = await uow.session.execute(stmt)
        return [Webhook.model_validate(row) for row in result.scalars().all()]


@router.post("", response_model=Webhook, status_code=status.HTTP_201_CREATED)
@inject
async def create_webhook(
    uow: FromDishka[PublicUnitOfWork], data: WebhookCreate
) -> Webhook:
    async with uow:
        model = WebhookModel(
            id=uuid.uuid4(),
            name=data.name,
            url=str(data.url),
            secret=generate_secret(),
            events=list(data.events),
            extra_headers=data.extra_headers,
            customer_id=_ANON,
            user_id=_ANON,
            is_active=True,
        )
        uow.session.add(model)
        await uow.session.flush()
        await uow.commit()
        return Webhook.model_validate(model)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_webhook(
    webhook_id: uuid.UUID, uow: FromDishka[PublicUnitOfWork]
) -> None:
    async with uow:
        stmt = select(WebhookModel).where(WebhookModel.id == webhook_id)
        result = await uow.session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        await uow.session.delete(model)
        await uow.commit()


@router.post("/{webhook_id}/test", response_model=WebhookDeliveryResult)
@inject
async def test_webhook(
    webhook_id: uuid.UUID, uow: FromDishka[PublicUnitOfWork]
) -> WebhookDeliveryResult:
    """Fire a canned `webhook.test` event at the registered URL."""
    async with uow:
        stmt = select(WebhookModel).where(WebhookModel.id == webhook_id)
        result = await uow.session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return await deliver(
        model,
        event="webhook.test",
        payload={"message": "forge webhook test"},
    )
