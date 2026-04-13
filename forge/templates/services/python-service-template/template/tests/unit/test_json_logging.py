"""Tests for service.observability.json_logging."""

import json
import logging
import sys

from service.observability.correlation import _correlation_id, set_correlation_id
from service.observability.json_logging import JsonFormatter


class TestJsonFormatter:
    def setup_method(self):
        self.formatter = JsonFormatter()
        self.logger = logging.getLogger("test.json_logging")
        # Ensure correlation ID is clean for each test
        set_correlation_id("")

    def _make_record(self, msg="hello", **extra):
        record = self.logger.makeRecord(
            name="test.json_logging",
            level=logging.INFO,
            fn="test.py",
            lno=1,
            msg=msg,
            args=(),
            exc_info=None,
            extra=extra,
        )
        return record

    def test_basic_format_is_valid_json(self):
        record = self._make_record("test message")
        output = self.formatter.format(record)
        payload = json.loads(output)
        assert payload["message"] == "test message"
        assert payload["level"] == "INFO"
        assert "timestamp" in payload

    def test_includes_correlation_id(self):
        set_correlation_id("abc123")
        record = self._make_record()
        payload = json.loads(self.formatter.format(record))
        assert payload["correlation_id"] == "abc123"

    def test_no_correlation_id(self):
        set_correlation_id("")
        record = self._make_record()
        payload = json.loads(self.formatter.format(record))
        assert "correlation_id" not in payload

    def test_extra_fields(self):
        record = self._make_record(customer_id="cust-1", method="GET", path="/api")
        payload = json.loads(self.formatter.format(record))
        assert payload["customer_id"] == "cust-1"
        assert payload["method"] == "GET"
        assert payload["path"] == "/api"

    def test_exception_info(self):
        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = sys.exc_info()
            record = self.logger.makeRecord(
                name="test", level=logging.ERROR, fn="test.py", lno=1,
                msg="failed", args=(), exc_info=exc_info,
            )
        payload = json.loads(self.formatter.format(record))
        assert payload["exception"]["type"] == "ValueError"
        assert payload["exception"]["message"] == "boom"
        assert isinstance(payload["exception"]["traceback"], list)
