"""``chat.*`` — chat UX adjuncts (file uploads, attachments)."""

from __future__ import annotations

from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
    register_option,
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
