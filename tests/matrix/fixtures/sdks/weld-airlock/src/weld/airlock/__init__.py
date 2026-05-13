"""weld.airlock stub."""

from typing import Any

DEFAULT_RETRY_POLICY: dict[str, Any] = {
    "max_attempts": 3,
    "initial_backoff_seconds": 0.5,
}


class AsyncAirlockClient:
    """Stub airlock SDK client."""

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    async def submit(self, *args: Any, **kwargs: Any) -> Any: ...

    async def fetch(self, *args: Any, **kwargs: Any) -> Any: ...
