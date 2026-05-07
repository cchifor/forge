"""``rag.*`` features — retrieval-augmented generation stack.

Wave C of the features-reorganization refactor. The largest feature
in scope: ``rag_pipeline`` (the canonical entry point, with embedding
loop + document ingestion + pgvector default), embedding-provider
variants (Voyage), reranker (Cohere), and per-backend integrations
(seven legacy ``rag_<backend>`` fragments + the newer port+adapter
``vector_store_*`` fragments per RFC-005 / ADR-002).

Cross-feature edge: ``rag_pipeline`` depends on
``conversation_persistence`` (in ``forge.features.conversation``).
``rag_sync_tasks`` additionally depends on ``background_tasks`` (in
``forge.features.async_work``). Both deps resolve at registry-freeze
time regardless of feature import order.
"""

from __future__ import annotations

from forge.features.rag import (  # noqa: F401, E402
    fragments,
    options,
)
