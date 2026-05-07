"""``async.*`` and ``queue.*`` features — off-thread job processing.

Wave B of the features-reorganization refactor. Combines the
background-task fragment (``background_tasks``) and the queue
port + adapters (``queue_port``, ``queue_redis``, ``queue_sqs``)
under one feature root since they're conceptually a single
async-work surface.

Note: ``async.rag_ingest_queue`` enables ``rag_sync_tasks`` whose
implementation lives under the rag/ feature (Wave C). Cross-feature
fragment references via name are fine — the resolver's freeze-time
audit ensures the graph is consistent regardless of which file
registers each fragment.
"""

from __future__ import annotations

from forge.features.async_work import (  # noqa: F401, E402
    fragments,
    options,
)
