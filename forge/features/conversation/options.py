"""``conversation.*`` and ``chat.*`` options — chat history + attachments."""

from __future__ import annotations

from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
    register_option,
)

register_option(
    Option(
        path="conversation.persistence",
        type=OptionType.BOOL,
        default=False,
        summary="SQLAlchemy Conversation / Message / ToolCall + migration.",
        description="""\
SQLAlchemy models + Pydantic schemas + a repository for Conversation,
Message, and ToolCall rows, plus the Alembic migration that creates
them. Rows are tenant + user scoped. This is the foundation the agent
stream persists history to.

BACKENDS: python
REQUIRES: migration 0002 applied (``alembic upgrade head``).""",
        category=FeatureCategory.CONVERSATIONAL_AI,
        stability="beta",
        enables={True: ("conversation_persistence",)},
    )
)


register_option(
    Option(
        path="chat.attachments",
        type=OptionType.BOOL,
        default=False,
        summary="/chat-files multipart + ChatFile model + local storage.",
        description="""\
Multipart upload + download endpoints under /api/v1/chat-files with
local-disk storage, configurable size + MIME allow-list, and a
ChatFile SQLAlchemy model + migration for users who want DB
persistence. The endpoint is storage-only by default (no DB write) so
dropping it in doesn't require Dishka DI changes.

BACKENDS: python
ENDPOINTS: /api/v1/chat-files (upload + download by id)
REQUIRES: conversation.persistence = true; UPLOAD_DIR writable.""",
        category=FeatureCategory.CONVERSATIONAL_AI,
        stability="beta",
        enables={True: ("file_upload",)},
    )
)
