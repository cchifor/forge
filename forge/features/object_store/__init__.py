"""``object_store.*`` features — blob storage port + adapters.

The ``object_store_port`` defines the abstract blob-storage interface;
``object_store_s3`` plugs in S3 / MinIO / R2 / Wasabi via aioboto3 and
``object_store_local`` ships a filesystem-backed adapter for dev /
single-node use.
"""

from __future__ import annotations

from forge.features.object_store import (  # noqa: F401, E402
    fragments,
    options,
)
