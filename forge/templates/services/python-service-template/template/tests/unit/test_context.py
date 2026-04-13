"""Tests for service.core.context."""

import pytest

from service.core.context import (
    get_customer_id,
    get_user_id,
    reset_context,
    set_context,
)


class TestContextVars:
    def test_set_and_get_customer_id(self):
        tokens = set_context("cust-1", "user-1")
        try:
            assert get_customer_id() == "cust-1"
        finally:
            reset_context(tokens)

    def test_set_and_get_user_id(self):
        tokens = set_context("cust-1", "user-1")
        try:
            assert get_user_id() == "user-1"
        finally:
            reset_context(tokens)

    def test_get_customer_id_unset_raises(self):
        with pytest.raises(ValueError, match="customer_id"):
            get_customer_id()

    def test_get_user_id_unset_raises(self):
        with pytest.raises(ValueError, match="user_id"):
            get_user_id()

    def test_reset_context_reverts(self):
        tokens = set_context("cust-1", "user-1")
        assert get_customer_id() == "cust-1"
        reset_context(tokens)
        with pytest.raises(ValueError):
            get_customer_id()
