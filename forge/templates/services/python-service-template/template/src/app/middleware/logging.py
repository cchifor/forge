import logging
import time
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
        if request.url.path in self.skip_paths:
            return await call_next(request)

        start_time = time.perf_counter()

        try:
            response = await call_next(request)
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
