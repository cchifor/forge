"""``object_store.*`` options — blob-storage backend selection."""

from __future__ import annotations

from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
    register_option,
)

register_option(
    Option(
        path="object_store.backend",
        type=OptionType.ENUM,
        default="none",
        options=("none", "s3", "local"),
        summary="Blob storage — AWS S3 / S3-compatible / local filesystem, behind ObjectStorePort.",
        description="""\
Selects which object-store implementation backs the ``ObjectStorePort``.
The ``s3`` adapter also handles MinIO / R2 / Wasabi (set S3_ENDPOINT_URL).
The ``local`` adapter writes under a filesystem root — dev / test only.

OPTIONS: none | s3 | local
BACKENDS: python
DEPENDENCY: aioboto3 (s3) | none (local)
ENV: AWS_REGION / S3_ENDPOINT_URL / OBJECT_STORE_ROOT""",
        category=FeatureCategory.PLATFORM,
        enables={
            "s3": ("object_store_port", "object_store_s3"),
            "local": ("object_store_port", "object_store_local"),
        },
    )
)
