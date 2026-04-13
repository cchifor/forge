"""Tests for app.services.health_service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.health import HealthStatus
from app.services.health_service import HealthService


class TestHealthService:
    @pytest.fixture
    def service(self):
        return HealthService()

    async def test_check_liveness(self, service):
        result = await service.check_liveness()
        assert result.status == HealthStatus.UP

    async def test_check_readiness_healthy(self, service):
        mock_uow = MagicMock()
        mock_repo = AsyncMock()
        mock_repo.ping_db.return_value = True
        mock_uow.repo.return_value = mock_repo

        result = await service.check_readiness(mock_uow)
        assert result.status == HealthStatus.UP
        assert "database" in result.components
        assert result.components["database"].status == HealthStatus.UP

    async def test_check_readiness_unhealthy(self, service):
        mock_uow = MagicMock()
        mock_repo = AsyncMock()
        mock_repo.ping_db.return_value = False
        mock_uow.repo.return_value = mock_repo

        result = await service.check_readiness(mock_uow)
        assert result.status == HealthStatus.DOWN
        assert result.components["database"].status == HealthStatus.DOWN
