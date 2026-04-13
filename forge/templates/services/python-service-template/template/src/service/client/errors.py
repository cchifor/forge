"""Errors for service-to-service communication."""

from __future__ import annotations

from typing import Any


class ServiceCallError(Exception):
    """Raised when a call to an external service fails."""

    def __init__(
        self,
        service: str,
        method: str,
        url: str,
        status_code: int | None = None,
        body: Any = None,
        cause: Exception | None = None,
    ):
        self.service = service
        self.method = method
        self.url = url
        self.status_code = status_code
        self.body = body
        msg = f"{service}: {method} {url}"
        if status_code:
            msg += f" -> {status_code}"
        super().__init__(msg)
        if cause:
            self.__cause__ = cause


class CircuitOpenError(ServiceCallError):
    """Raised when the circuit breaker is open and the call is rejected."""

    def __init__(self, service: str, retry_after_seconds: float):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            service=service,
            method="*",
            url="*",
            status_code=None,
            body=None,
        )

    def __str__(self) -> str:
        return (
            f"Circuit breaker open for {self.service}. Retry after {self.retry_after_seconds:.0f}s."
        )
