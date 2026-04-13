"""Tests for the task handler registry."""

import pytest

from service.tasks.registry import (
    _HANDLERS,
    get_handler,
    registered_types,
    task_handler,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Clear the registry before and after each test."""
    original = _HANDLERS.copy()
    _HANDLERS.clear()
    yield
    _HANDLERS.clear()
    _HANDLERS.update(original)


class TestTaskRegistry:
    def test_register_handler(self):
        @task_handler("test_task")
        async def handle_test(payload: dict):
            return {"done": True}

        assert "test_task" in registered_types()
        assert get_handler("test_task") is handle_test

    def test_unknown_handler_returns_none(self):
        assert get_handler("nonexistent") is None

    def test_registered_types(self):
        @task_handler("type_a")
        async def a(p):
            pass

        @task_handler("type_b")
        async def b(p):
            pass

        types = registered_types()
        assert "type_a" in types
        assert "type_b" in types

    def test_overwrite_warning(self):
        @task_handler("dup")
        async def first(p):
            pass

        @task_handler("dup")
        async def second(p):
            pass

        assert get_handler("dup") is second
