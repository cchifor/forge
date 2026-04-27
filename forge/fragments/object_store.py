"""Object-store port + adapters (1.0.0a2+).

``object_store_port`` defines the abstract blob storage interface;
``object_store_s3`` plugs in S3/MinIO via aioboto3 and
``object_store_local`` ships a filesystem-backed adapter for dev/
single-node use.
"""

from __future__ import annotations

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec

register_fragment(
    Fragment(
        name="object_store_port",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="object_store_port/python",
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="object_store_s3",
        depends_on=("object_store_port",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="object_store_s3/python",
                dependencies=("aioboto3>=13.2.0",),
                env_vars=(
                    ("AWS_REGION", "us-east-1"),
                    ("S3_ENDPOINT_URL", ""),
                    ("AWS_ACCESS_KEY_ID", ""),
                    ("AWS_SECRET_ACCESS_KEY", ""),
                ),
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="object_store_local",
        depends_on=("object_store_port",),
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="object_store_local/python",
                env_vars=(("OBJECT_STORE_ROOT", "/var/lib/forge/objects"),),
            ),
        },
    )
)
