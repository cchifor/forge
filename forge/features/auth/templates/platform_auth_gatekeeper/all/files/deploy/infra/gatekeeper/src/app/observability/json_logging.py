"""Structured JSON log formatter.

In production, every log line should be a single JSON object so it can be
ingested by Loki / ELK / CloudWatch without regex parsing.  In development,
human-readable text is still preferred.

Usage in config/production.yaml::

    logging:
      formatters:
        json:
          "()": app.observability.json_logging.JsonFormatter
          service: gatekeeper
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


class JsonFormatter(logging.Formatter):
    """Emits each log record as a single-line JSON object.

    Parameters
    ----------
    service : str
        Logical service name injected into every log line so aggregated
        logs (Loki, ELK) can be filtered by service.
    """

    def __init__(self, *args: Any, service: str = "gatekeeper", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": dt.datetime.fromtimestamp(
                record.created, tz=dt.UTC
            ).isoformat(),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Merge structured extra fields (passed via logger.info("msg", extra={...}))
        for key in (
            "correlation_id",
            "customer_id",
            "user_id",
            "source",
            "method",
            "path",
            "status",
            "duration_ms",
            "error",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value

        # Exception info
        if record.exc_info and record.exc_info[1] is not None:
            payload["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        return json.dumps(payload, default=str, ensure_ascii=False)
