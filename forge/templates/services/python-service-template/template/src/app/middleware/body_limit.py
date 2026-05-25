"""ASGI middleware that enforces a maximum request body size.

Rejects requests whose ``Content-Length`` header exceeds the configured
limit with HTTP 413 (Payload Too Large). For chunked / streaming bodies
that omit ``Content-Length``, the middleware counts bytes during streaming
and aborts as soon as the limit is exceeded.
"""

import logging

from starlette.requests import HTTPConnection
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Fallback when instantiated without explicit max_body_size.
# In practice, main.py passes settings.audit.max_body_size (50 KiB).
DEFAULT_MAX_BODY_SIZE: int = 1_048_576  # 1 MiB


class ContentSizeLimitMiddleware:
    """Pure-ASGI middleware — no BaseHTTPMiddleware overhead.

    Parameters
    ----------
    app:
        The next ASGI application in the stack.
    max_body_size:
        Maximum allowed request body in bytes. Defaults to 1 MiB.
    """

    def __init__(self, app: ASGIApp, max_body_size: int = DEFAULT_MAX_BODY_SIZE) -> None:
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        conn = HTTPConnection(scope)
        content_length = conn.headers.get("content-length")

        # Fast-path: Content-Length header present — reject before reading.
        if content_length is not None:
            try:
                if int(content_length) > self.max_body_size:
                    response = PlainTextResponse(
                        "Request body too large", status_code=413
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                pass  # Non-integer Content-Length — let downstream handle.

        # Slow-path: stream body chunks and enforce limit on the fly.
        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                received += len(body)
                if received > self.max_body_size:
                    raise _BodyTooLarge()
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _BodyTooLarge:
            if not response_started:
                response = PlainTextResponse(
                    "Request body too large", status_code=413
                )
                await response(scope, receive, send)


class _BodyTooLarge(Exception):
    """Internal signal — never escapes the middleware."""
