"""Built-in connector implementations (vendored, self-contained).

Each builtin depends on a different slice of the dependency tree:

* ``fs``     — pure stdlib + pydantic
* ``sample`` — pure stdlib + pydantic
* ``http``   — httpx (a base-template dependency)
* ``s3``     — boto3 (install separately if you enable the s3 backend)
* ``sql``    — an async SQLAlchemy driver (aiosqlite is a base dependency;
               install asyncpg for Postgres)

Importing this package gracefully skips connectors whose dependency is
not installed, so :func:`app.connectors.registry.build_default_connector_registry`
registers only the ones a service can actually run.

Note: the platform's gatekeeper-coupled ``MCPConnector`` is intentionally
not vendored here — it depended on a private auth SDK. Register your own
MCP adapter via ``ConnectorRegistry.register`` if you need one.
"""

from __future__ import annotations

__all__: list[str] = []

try:
    from app.connectors.builtin.fs import FilesystemConnector  # noqa: F401

    __all__.append("FilesystemConnector")
except ImportError:
    pass

try:
    # Sample connector has no extra deps — pure stdlib + pydantic. Kept
    # behind the same try/except for shape-consistency, even though the
    # import never fails.
    from app.connectors.builtin.sample import SampleConnector  # noqa: F401

    __all__.append("SampleConnector")
except ImportError:
    pass

try:
    from app.connectors.builtin.http import HTTPConnector  # noqa: F401

    __all__.append("HTTPConnector")
except ImportError:
    pass

try:
    from app.connectors.builtin.s3 import S3Connector  # noqa: F401

    __all__.append("S3Connector")
except ImportError:
    pass

try:
    from app.connectors.builtin.sql import SQLConnector  # noqa: F401

    __all__.append("SQLConnector")
except ImportError:
    pass
