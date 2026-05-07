"""``conversation.*`` and ``chat.*`` features — chat history persistence + uploads.

Wave C of the features-reorganization refactor. Owns the
conversation persistence foundation (``conversation_persistence``)
and the file-upload extension (``file_upload``); both share the
same SQLAlchemy schema, so they sit in one feature dir.

Cross-feature edge: ``rag.*`` and ``agent.*`` both depend on
``conversation_persistence`` (by fragment name). The resolver
freezes the registry after every feature has registered, so the
order of feature imports doesn't matter.
"""

from __future__ import annotations

from forge.features.conversation import (  # noqa: F401, E402
    fragments,
    options,
)
