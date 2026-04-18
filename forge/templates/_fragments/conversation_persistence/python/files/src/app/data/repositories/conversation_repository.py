"""Repository for conversations and their messages.

Intentionally does not extend the generic ``AsyncBaseRepository`` — the
cascade/relationship surface is richer than the base repo's schema-mapping
machinery handles cleanly. Direct SQLAlchemy here is more legible.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import desc, select
from sqlalchemy.orm import selectinload

from app.data.models.conversation import (
    Conversation as ConversationModel,
    Message as MessageModel,
    ToolCall as ToolCallModel,
)
from app.data.repositories.base_tenant_aware import TenantScopedRepository
from app.domain.conversation import (
    Conversation,
    Message,
    MessageRole,
    ToolCallStatus,
)


class ConversationRepository(TenantScopedRepository):
    """Tenant-scoped. Every read/write is constrained by the caller's Account,
    which must carry both `customer_id` and `user_id` — a PublicUnitOfWork
    (account=None) cannot instantiate this repository.
    """

    async def create_conversation(self, title: str = "New conversation") -> Conversation:
        model = ConversationModel(
            title=title,
            customer_id=self.customer_id,
            user_id=self.user_id,
        )
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return Conversation.model_validate(model)

    async def get_conversation(self, conversation_id: uuid.UUID) -> Conversation | None:
        stmt = (
            select(ConversationModel)
            .where(
                ConversationModel.id == conversation_id,
                ConversationModel.customer_id == self.customer_id,
            )
            .options(selectinload(ConversationModel.messages).selectinload(MessageModel.tool_calls))
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return Conversation.model_validate(model) if model else None

    async def list_conversations(self, *, limit: int = 50, offset: int = 0) -> Sequence[Conversation]:
        stmt = (
            select(ConversationModel)
            .where(
                ConversationModel.customer_id == self.customer_id,
                ConversationModel.user_id == self.user_id,
                ConversationModel.archived_at.is_(None),
            )
            .order_by(desc(ConversationModel.updated_at))
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return [Conversation.model_validate(m) for m in result.scalars().all()]

    async def append_message(
        self,
        *,
        conversation_id: uuid.UUID,
        role: MessageRole,
        content: str,
        metadata_json: dict | None = None,
    ) -> Message:
        model = MessageModel(
            conversation_id=conversation_id,
            customer_id=self.customer_id,
            role=role.value,
            content=content,
            metadata_json=metadata_json,
        )
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return Message.model_validate(model)

    async def record_tool_call(
        self,
        *,
        message_id: uuid.UUID,
        tool_name: str,
        arguments: dict,
        result: dict | None = None,
        status: ToolCallStatus = ToolCallStatus.SUCCEEDED,
        error: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        tc = ToolCallModel(
            message_id=message_id,
            customer_id=self.customer_id,
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            status=status.value,
            error=error,
            duration_ms=duration_ms,
        )
        self.session.add(tc)
        await self.session.flush()

    async def archive(self, conversation_id: uuid.UUID) -> bool:
        from datetime import UTC, datetime

        stmt = select(ConversationModel).where(
            ConversationModel.id == conversation_id,
            ConversationModel.customer_id == self.customer_id,
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return False
        model.archived_at = datetime.now(UTC)
        await self.session.flush()
        return True
