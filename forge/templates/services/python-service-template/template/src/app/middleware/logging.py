import logging
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterable, Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

access_logger = logging.getLogger("api.access")

CORRELATION_HEADER = "x-request-id"


def _ensure_correlation_id(request: Request) -> str:
    """Return the correlation id for this request, generating one if absent.

    Base-level invariant: every request gets a correlation id in
    ``request.state.correlation_id`` and echoed in the ``X-Request-ID``
    response header — regardless of whether the ``correlation_id`` fragment
    is enabled. The fragment (if present) additionally propagates the id
    through async ``ContextVar``s so downstream tasks see the same value.
    """
    existing = getattr(request.state, "correlation_id", None)
    if existing:
        return str(existing)
    incoming = request.headers.get(CORRELATION_HEADER)
    cid = incoming or uuid.uuid4().hex
    request.state.correlation_id = cid
    return cid


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        logger: logging.Logger = access_logger,
        skip_paths: list[str] | None = None,
    ):
        super().__init__(app)
        self.logger = logger
        self.skip_paths = set(skip_paths or [])

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Generate / read + stash before any log entry, so even the skip-path
        # short-circuit and error paths carry a correlation id.
        correlation_id = _ensure_correlation_id(request)

        if request.url.path in self.skip_paths:
            response = await call_next(request)
            response.headers[CORRELATION_HEADER] = correlation_id
            return response

        start_time = time.perf_counter()

        try:
            response = await call_next(request)
            response.headers[CORRELATION_HEADER] = correlation_id
            if isinstance(response, StreamingResponse):
                response.body_iterator = self._stream_response_wrapper(
                    response.body_iterator, request, response.status_code, start_time
                )
            else:
                self._log_request(request, response.status_code, start_time)
            return response
        except Exception as e:
            self._log_request(request, 500, start_time, error=e)
            raise e

    async def _stream_response_wrapper(
        self,
        body_iterator: AsyncIterable[str | bytes],
        request: Request,
        status_code: int,
        start_time: float,
    ) -> AsyncGenerator[str | bytes]:
        try:
            async for chunk in body_iterator:
                yield chunk
        finally:
            self._log_request(request, status_code, start_time)

    def _log_request(
        self,
        request: Request,
        status_code: int,
        start_time: float,
        error: Exception | None = None,
    ) -> None:
        duration = (time.perf_counter() - start_time) * 1000
        source = f"{request.client.host}:{request.client.port}" if request.client else "unknown"
        # Enrich with correlation and tenant context
        correlation_id = getattr(request.state, "correlation_id", None)
        user = getattr(request.state, "user", None)

        log_data = {
            "source": source,
            "method": request.method,
            "path": request.url.path,
            "query": dict(request.query_params),
            "status": status_code,
            "duration_ms": round(duration, 2),
        }
        if correlation_id:
            log_data["correlation_id"] = correlation_id
        if user:
            log_data["customer_id"] = getattr(user, "customer_id", None)
            log_data["user_id"] = getattr(user, "id", None)
        resource = f"{request.method} {request.url.path}"
        result = f"{status_code} [{duration:.1f}ms]"

        if error:
            log_data["error"] = str(error)
            self.logger.error(f"{source} => {resource} => {error}", extra=log_data)
        else:
            self.logger.info(f"{source} => {resource} => {result}", extra=log_data)
