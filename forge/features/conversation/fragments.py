"""Conversation persistence + file uploads — shared SQLAlchemy foundation.

``conversation_persistence`` ships the Conversation / Message / ToolCall
models + repository + Alembic migration; ``file_upload`` adds the
ChatFile model + multipart endpoint and depends on the same schema.

Both are tier-3 (Python-only) by auto-derivation. ``rag.*`` and
``agent.*`` depend on ``conversation_persistence`` by name — cross-
feature dependencies are resolved at registry-freeze time.
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _impl(name: str, lang: str) -> str:
    return str(_TEMPLATES / name / lang)


register_fragment(
    Fragment(
        name="conversation_persistence",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("conversation_persistence", "python"),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="file_upload",
        depends_on=("conversation_persistence",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("file_upload", "python"),
                dependencies=("python-multipart>=0.0.20",),
                env_vars=(
                    ("UPLOAD_DIR", "./uploads"),
                    ("MAX_UPLOAD_SIZE", "10485760"),
                    ("ALLOWED_MIME_TYPES", ""),
                ),
            ),
        },
    )
)
