"""SQLAdmin wrapper mounted at /admin.

Exposure is gated by ``ADMIN_PANEL_MODE``:

  - ``disabled`` (default) — not mounted
  - ``dev``  — mounted only when ``ENVIRONMENT == "local"`` or ``"development"``
  - ``all``  — mounted in every environment; **requires** a reverse-proxy
               auth layer in front that populates Gatekeeper-style headers
               (``x-gatekeeper-customer-id``, ``x-gatekeeper-user-id``).
               Refuses to mount otherwise.

Every ``ModelView`` inherits from ``TenantScopedModelView``, which filters
list / get queries by the authenticated caller's ``customer_id`` so one
tenant's admin cannot see another tenant's rows. Models without a
``customer_id`` column (audit_log intentionally records all tenants) opt
out by setting ``tenant_scoped = False``.

Uses its own AsyncEngine (separate from Dishka's) so the Admin UI can render
even before the DI container finishes wiring. The extra pool cost is
negligible since admin traffic is human-scale.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from fastapi import FastAPI

logger = logging.getLogger(__name__)


_CUSTOMER_HEADER_CANDIDATES = (
    "x-gatekeeper-customer-id",
    "x-customer-id",
    "x-gatekeeper-user-id",
)


def _tenant_id_from_request(request: Any) -> uuid.UUID | None:
    """Pull the caller's tenant id from gateway-provided headers.

    Returns None when no header is present; the scoped view treats that as
    "empty result set" to fail closed.
    """
    for header in _CUSTOMER_HEADER_CANDIDATES:
        raw = request.headers.get(header)
        if raw:
            try:
                return uuid.UUID(raw)
            except ValueError:
                return None
    return None


def _build_tenant_scoped_base() -> tuple[Any, Any]:
    """Return (TenantScopedModelView, ModelView) or (None, None) if missing deps."""
    try:
        from sqladmin import ModelView  # type: ignore
    except ImportError:
        return None, None

    class TenantScopedModelView(ModelView):
        """Filters list and detail queries by the authenticated tenant.

        Subclasses that target a model without a ``customer_id`` column
        (e.g., global audit log) set ``tenant_scoped = False``.
        """

        tenant_scoped: bool = True

        def _tenant_filter(self, request: Any) -> Any | None:
            if not self.tenant_scoped:
                return None
            customer_id_col = getattr(self.model, "customer_id", None)
            if customer_id_col is None:
                return None
            tenant_id = _tenant_id_from_request(request)
            if tenant_id is None:
                # Fail closed: return a clause that matches no rows rather
                # than exposing all tenants' data to an unauthenticated caller.
                return customer_id_col == uuid.UUID(int=0)
            return customer_id_col == tenant_id

        def list_query(self, request: Any) -> Any:
            stmt = super().list_query(request)
            clause = self._tenant_filter(request)
            return stmt.where(clause) if clause is not None else stmt

        def get_object_query(self, request: Any, pk: Any) -> Any:
            stmt = super().get_object_query(request, pk)
            clause = self._tenant_filter(request)
            return stmt.where(clause) if clause is not None else stmt

    return TenantScopedModelView, ModelView


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

    if mode == "all" and os.environ.get("ADMIN_PANEL_AUTH_ACKNOWLEDGED") != "1":
        logger.error(
            "ADMIN_PANEL_MODE=all refuses to mount without "
            "ADMIN_PANEL_AUTH_ACKNOWLEDGED=1. Put /admin behind a reverse "
            "proxy that sets x-gatekeeper-customer-id / x-gatekeeper-user-id "
            "before setting the acknowledgement, or keep mode=dev."
        )
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
    TenantScopedModelView, ModelView = _build_tenant_scoped_base()
    if TenantScopedModelView is None or ModelView is None:
        return []

    views: list[Any] = []

    # Base always-on models.
    try:
        from app.data.models.item import ItemModel  # type: ignore

        class ItemAdmin(TenantScopedModelView, model=ItemModel):
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

        class AuditAdmin(TenantScopedModelView, model=AuditLog):
            # Audit log is intentionally cross-tenant for SOC2 / compliance
            # reviewers who need to see all activity. Do not expose at
            # mode=all without a separate "auditor" role gate upstream.
            tenant_scoped = False
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

        class ConversationAdmin(TenantScopedModelView, model=ConvModel):
            name = "Conversation"
            name_plural = "Conversations"
            column_list = [ConvModel.id, ConvModel.title, ConvModel.created_at]
            column_searchable_list = [ConvModel.title]

        class MessageAdmin(TenantScopedModelView, model=MsgModel):
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

        class WebhookAdmin(TenantScopedModelView, model=Webhook):
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
