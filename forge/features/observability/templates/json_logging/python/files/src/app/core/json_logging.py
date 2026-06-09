"""Structured JSON log formatter.

In production every log line should be a single JSON object so it can be
ingested by Loki / ELK / CloudWatch without regex parsing. Each line is
enriched with the request correlation id and any structured ``extra=`` fields.

Wire it from your logging config (e.g. ``config/production.yaml``)::

    logging:
      formatters:
        json:
          "()": app.core.json_logging.JsonFormatter
          service: my-service
      handlers:
        console:
          class: logging.StreamHandler
          formatter: json
          stream: ext://sys.stdout
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import traceback
from typing import Any

from forge_core.observability.correlation import get_correlation_id


class JsonFormatter(logging.Formatter):
    """Emits each log record as a single-line JSON object.

    Parameters
    ----------
    service : str
        Logical service name injected into every log line so aggregated logs
        can be filtered by service.
    """

    def __init__(self, *args: Any, service: str = "unknown", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": dt.datetime.fromtimestamp(record.created, tz=dt.UTC).isoformat(),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Correlation context (set by the correlation-id middleware / ContextVar).
        correlation_id = get_correlation_id()
        if correlation_id:
            payload["correlation_id"] = correlation_id

        # Merge structured extra fields (logger.info("msg", extra={...})).
        for key in (
            "customer_id",
            "user_id",
            "tenant_slug",
            "source",
            "method",
            "path",
            "status",
            "duration_ms",
            "error",
            "query",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value

        # Exception info.
        if record.exc_info and record.exc_info[1] is not None:
            payload["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        return json.dumps(payload, default=str, ensure_ascii=False)
