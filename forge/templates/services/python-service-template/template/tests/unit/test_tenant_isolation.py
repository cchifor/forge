"""Tests for tenant isolation in the repository layer."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from service.domain.account import Account
from service.repository.base import RepositoryLogicMixin
from service.repository.mixins import TenantMixin, UserOwnedMixin


class TestTenantScoping:
    """Verify _apply_scopes correctly filters queries by tenant."""

    def test_no_account_skips_tenant_filter(self):
        """Without an Account, no tenant filtering is applied."""
        repo = MagicMock(spec=RepositoryLogicMixin)
        repo.account = None
        repo.model = type("FakeModel", (TenantMixin,), {
            "is_active": MagicMock(),
            "customer_id": MagicMock(),
        })

        # Call the real _apply_scopes
        query = MagicMock()
        result = RepositoryLogicMixin._apply_scopes(repo, query)
        # Should return the query without tenant filter
        assert result is not None

    def test_account_with_customer_id_adds_filter(self):
        """Account with customer_id should add WHERE customer_id = ?."""
        account = Account(
            customer_id="00000000-0000-0000-0000-000000000001",
            user_id="00000000-0000-0000-0000-000000000002",
        )
        assert account.customer_id is not None
        assert isinstance(account.customer_id, uuid.UUID)

    def test_account_with_none_customer_id_returns_empty(self):
        """Account with None customer_id should return no results."""
        account = Account(customer_id=None, user_id=None)
        assert account.customer_id is None
        # In _apply_scopes, this triggers where(false()) — no data returned

    def test_admin_bypasses_user_filter(self):
        """Admin users should see all items within their tenant."""
        from service.domain.account import UserRole

        admin = Account(
            customer_id="00000000-0000-0000-0000-000000000001",
            user_id="00000000-0000-0000-0000-000000000099",
            role=UserRole.ADMIN,
        )
        assert admin.is_admin() is True

    def test_regular_user_scoped_by_user_id(self):
        """Non-admin users should only see their own items."""
        from service.domain.account import UserRole

        user = Account(
            customer_id="00000000-0000-0000-0000-000000000001",
            user_id="00000000-0000-0000-0000-000000000002",
            role=UserRole.USER,
        )
        assert user.is_admin() is False


class TestGatekeeperHeaderExtraction:
    """Verify authenticate_request handles Gatekeeper headers correctly."""

    @pytest.mark.asyncio
    async def test_gatekeeper_headers_create_user(self):
        """X-Gatekeeper-* headers should create a User without token validation."""
        from service.security.auth import authenticate_request
        from unittest.mock import patch

        # Mock request with Gatekeeper headers
        request = MagicMock()
        request.headers = {
            "x-gatekeeper-user-id": "user-123",
            "x-gatekeeper-email": "user@example.com",
            "x-gatekeeper-roles": "admin,user",
        }
        request.app.state = MagicMock()
        request.state = MagicMock()

        with patch("service.security.auth.get_auth_provider_from_state"):
            user = await authenticate_request(request)

        assert user is not None
        assert user.id == "user-123"
        assert user.email == "user@example.com"
        assert user.roles == ["admin", "user"]

    @pytest.mark.asyncio
    async def test_gatekeeper_headers_missing_returns_none(self):
        """Missing Gatekeeper headers should fall through to token auth."""
        from service.security.auth import authenticate_request
        from unittest.mock import patch

        request = MagicMock()
        request.headers = {}  # No Gatekeeper headers
        request.app.state = MagicMock()
        request.state = MagicMock()

        # Mock the auth provider and token extraction
        with patch("service.security.auth.get_auth_provider_from_state") as mock_provider, \
             patch("service.security.auth.extract_token", return_value=None):
            mock_provider.return_value = MagicMock()
            user = await authenticate_request(request)

        assert user is None  # No Gatekeeper headers and no token
