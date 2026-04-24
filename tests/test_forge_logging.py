"""Tests for forge's own structured logging (P2.2)."""

from __future__ import annotations

import io
import json
import logging

import pytest

from forge.logging import configure_logging, get_logger, log_event


@pytest.fixture(autouse=True)
def _reset_forge_root():
    root = logging.getLogger("forge")
    saved_handlers = list(root.handlers)
    saved_level = root.level
    for h in list(root.handlers):
        if getattr(h, "_forge_owned", False):
            root.removeHandler(h)
    yield
    for h in list(root.handlers):
        if getattr(h, "_forge_owned", False):
            root.removeHandler(h)
    root.level = saved_level
    # Restore user-installed handlers untouched above.
    for h in saved_handlers:
        if not getattr(h, "_forge_owned", False) and h not in root.handlers:
            root.addHandler(h)


def test_get_logger_namespaces_to_forge():
    assert get_logger("plugins").name == "forge.plugins"
    assert get_logger("forge.plugins").name == "forge.plugins"


def test_text_format_renders_event_key_value_pairs():
    buf = io.StringIO()
    configure_logging(level="INFO", fmt="text", stream=buf)
    logger = get_logger("tests")
    log_event(logger, "fragment.applied", fragment="demo", duration_ms=42)
    out = buf.getvalue()
    assert "fragment.applied" in out
    assert "event=fragment.applied" in out
    assert "fragment=demo" in out
    assert "duration_ms=42" in out


def test_json_format_emits_valid_json_per_line():
    buf = io.StringIO()
    configure_logging(level="INFO", fmt="json", stream=buf)
    logger = get_logger("tests")
    log_event(logger, "plugin.loaded", plugin="p1", options_added=3)
    line = buf.getvalue().strip().splitlines()[0]
    parsed = json.loads(line)
    assert parsed["event"] == "plugin.loaded"
    assert parsed["plugin"] == "p1"
    assert parsed["options_added"] == 3
    assert parsed["logger"] == "forge.tests"
    assert parsed["level"] == "INFO"
    assert "ts" in parsed


def test_configure_logging_is_idempotent():
    buf_a = io.StringIO()
    configure_logging(level="INFO", fmt="text", stream=buf_a)
    buf_b = io.StringIO()
    configure_logging(level="INFO", fmt="text", stream=buf_b)
    logger = get_logger("tests")
    log_event(logger, "x")
    # Only the latest stream receives output.
    assert buf_a.getvalue() == ""
    assert "event=x" in buf_b.getvalue()


def test_log_event_respects_custom_level():
    buf = io.StringIO()
    configure_logging(level="WARNING", fmt="text", stream=buf)
    logger = get_logger("tests")
    log_event(logger, "info.only", level=logging.INFO)
    log_event(logger, "warning.real", level=logging.WARNING)
    out = buf.getvalue()
    assert "info.only" not in out
    assert "warning.real" in out


def test_env_var_fallback(monkeypatch):
    monkeypatch.setenv("FORGE_LOG_FORMAT", "json")
    monkeypatch.setenv("FORGE_LOG_LEVEL", "DEBUG")
    buf = io.StringIO()
    configure_logging(stream=buf)
    logger = get_logger("tests")
    log_event(logger, "debug.check", level=logging.DEBUG, detail="ok")
    line = buf.getvalue().strip().splitlines()[0]
    assert json.loads(line)["event"] == "debug.check"
