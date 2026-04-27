"""``conversation.*`` — chat history persistence."""

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
