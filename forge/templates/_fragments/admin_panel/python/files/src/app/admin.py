"""SQLAdmin wrapper mounted at /admin.

Exposure is gated by ``ADMIN_PANEL_MODE``:

  - ``disabled`` (default) — not mounted
  - ``dev``  — mounted only when ``ENVIRONMENT == "local"`` or ``"development"``
  - ``all``  — mounted in every environment

Uses its own AsyncEngine (separate from Dishka's) so the Admin UI can render
even before the DI container finishes wiring. The extra pool cost is
negligible since admin traffic is human-scale.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI

logger = logging.getLogger(__name__)


def mount_admin(app: FastAPI) -> None:
    mode = os.environ.get("ADMIN_PANEL_MODE", "disabled").strip().lower()
    env = os.environ.get("ENVIRONMENT", "local").strip().lower()

    if mode == "disabled":
        return
    if mode == "dev" and env not in {"local", "development", "dev"}:
        return
    if mode not in {"dev", "all"}:
        logger.warning("ADMIN_PANEL_MODE=%r unrecognized; disabling admin", mode)
        return

    try:
        from sqladmin import Admin  # type: ignore
        from sqlalchemy.ext.asyncio import create_async_engine
    except ImportError as e:
        logger.warning("admin_panel requested but sqladmin missing: %s", e)
        return

    url = os.environ.get("DATABASE_URL")
    if not url:
        logger.warning("admin_panel: DATABASE_URL unset; skipping mount")
        return
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(url)
    admin = Admin(app, engine, title="forge admin")

    for view in _auto_views():
        try:
            admin.add_view(view)
        except Exception as e:  # noqa: BLE001
            logger.warning("admin view %s skipped: %s", view.__name__, e)

    logger.info("admin panel mounted at /admin (mode=%s, env=%s)", mode, env)


def _auto_views() -> list[Any]:
    """Best-effort: expose ModelViews for whichever opt-in tables exist."""
    from sqladmin import ModelView  # type: ignore

    views: list[Any] = []

    # Base always-on models.
    try:
        from app.data.models.item import ItemModel  # type: ignore

        class ItemAdmin(ModelView, model=ItemModel):
            name = "Item"
            name_plural = "Items"
            column_list = [
                ItemModel.id,
                ItemModel.name,
                ItemModel.status,
                ItemModel.created_at,
            ]
            column_searchable_list = [ItemModel.name]

        views.append(ItemAdmin)
    except ImportError:
        pass

    try:
        from app.data.models.audit import AuditLog  # type: ignore

        class AuditAdmin(ModelView, model=AuditLog):
            name = "Audit log"
            name_plural = "Audit logs"
            column_list = [
                AuditLog.id,
                AuditLog.action,
                AuditLog.username,
                AuditLog.path,
                AuditLog.status_code,
                AuditLog.created_at,
            ]

        views.append(AuditAdmin)
    except ImportError:
        pass

    # Opt-in feature tables.
    try:
        from app.data.models.conversation import (  # type: ignore
            Conversation as ConvModel,
            Message as MsgModel,
        )

        class ConversationAdmin(ModelView, model=ConvModel):
            name = "Conversation"
            name_plural = "Conversations"
            column_list = [ConvModel.id, ConvModel.title, ConvModel.created_at]
            column_searchable_list = [ConvModel.title]

        class MessageAdmin(ModelView, model=MsgModel):
            name = "Message"
            name_plural = "Messages"
            column_list = [
                MsgModel.id,
                MsgModel.role,
                MsgModel.conversation_id,
                MsgModel.created_at,
            ]

        views.append(ConversationAdmin)
        views.append(MessageAdmin)
    except ImportError:
        pass

    try:
        from app.data.models.webhook import Webhook  # type: ignore

        class WebhookAdmin(ModelView, model=Webhook):
            name = "Webhook"
            name_plural = "Webhooks"
            column_list = [
                Webhook.id,
                Webhook.name,
                Webhook.url,
                Webhook.is_active,
                Webhook.created_at,
            ]

        views.append(WebhookAdmin)
    except ImportError:
        pass

    return views
