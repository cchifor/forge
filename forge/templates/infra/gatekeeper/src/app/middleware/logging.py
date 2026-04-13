import logging
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterable, Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

access_logger = logging.getLogger("api.access")


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
        # Propagate or generate a request correlation ID.
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:8]
        request.state.request_id = request_id

        if any(request.url.path.startswith(p) for p in self.skip_paths):
            response = await call_next(request)
            response.headers["X-Request-Id"] = request_id
            return response

        start_time = time.perf_counter()

        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = request_id

            if isinstance(response, StreamingResponse):
                response.body_iterator = self._stream_response_wrapper(
                    response.body_iterator, request, response.status_code, start_time
                )
            else:
                self._log_request(request, response.status_code, start_time)

            return response

        except Exception as e:
            self._log_request(request, 500, start_time, error=e)
            raise

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

        source = (
            f"{request.client.host}:{request.client.port}"
            if request.client
            else "unknown"
        )

        request_id = getattr(request.state, "request_id", "?")

        log_data = {
            "request_id": request_id,
            "source": source,
            "method": request.method,
            "path": request.url.path,
            "query": dict(request.query_params),
            "status": status_code,
            "duration_ms": round(duration, 2),
        }

        resource = f"{request.method} {request.url.path}"
        result = f"{status_code} [{duration:.1f}ms]"
        prefix = f"[{request_id}] {source}"

        if error:
            log_data["error"] = str(error)
            self.logger.error(f"{prefix} => {resource} => {error}", extra=log_data)
        else:
            self.logger.info(f"{prefix} => {resource} => {result}", extra=log_data)
