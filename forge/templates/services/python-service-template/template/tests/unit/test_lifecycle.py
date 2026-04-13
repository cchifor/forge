"""Unit tests for the application lifecycle orchestration."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.lifecycle import AppLifecycle


class TestBootstrap:
    """Tests for AppLifecycle.bootstrap (build-time wiring)."""

    @patch("app.core.lifecycle.auth")
    @patch("app.core.lifecycle.setup_dishka")
    @patch("app.core.lifecycle.make_async_container")
    @patch("app.core.lifecycle.AppLifecycle._setup_logging")
    def test_bootstrap_calls_setup_logging(
        self, mock_logging, mock_container, mock_dishka, mock_auth,
    ):
        app = MagicMock()
        config = MagicMock()
        config.security.auth.enabled = False

        AppLifecycle.bootstrap(app, config)

        mock_logging.assert_called_once_with(config)

    @patch("app.core.lifecycle.auth")
    @patch("app.core.lifecycle.setup_dishka")
    @patch("app.core.lifecycle.make_async_container")
    @patch("app.core.lifecycle.AppLifecycle._setup_logging")
    def test_bootstrap_initialises_di_container(
        self, mock_logging, mock_container, mock_dishka, mock_auth,
    ):
        app = MagicMock()
        config = MagicMock()
        config.security.auth.enabled = False

        AppLifecycle.bootstrap(app, config)

        mock_container.assert_called_once()
        mock_dishka.assert_called_once()


class TestLifespan:
    """Tests for async lifespan context manager."""

    @pytest.mark.asyncio
    async def test_raises_without_container(self):
        app = MagicMock()
        app.state.dishka_container = None

        with pytest.raises(RuntimeError, match="DI Container"):
            async with AppLifecycle.lifespan(app):
                pass

    @pytest.mark.asyncio
    @patch.object(AppLifecycle, "_on_shutdown", new_callable=AsyncMock)
    @patch.object(AppLifecycle, "_on_startup", new_callable=AsyncMock)
    async def test_calls_startup_and_shutdown(
        self, mock_startup, mock_shutdown,
    ):
        container = AsyncMock()
        config = MagicMock()
        config.server.host = "0.0.0.0"
        config.server.port = 5000
        container.get = AsyncMock(return_value=config)

        app = MagicMock()
        app.state.dishka_container = container

        async with AppLifecycle.lifespan(app):
            mock_startup.assert_awaited_once_with(container)

        mock_shutdown.assert_awaited_once_with(container)


class TestShutdown:
    """Tests for _on_shutdown cleanup."""

    @pytest.mark.asyncio
    async def test_shutdown_closes_container(self):
        container = AsyncMock()
        AppLifecycle._task_runner = None

        await AppLifecycle._on_shutdown(container)

        container.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_stops_task_runner(self):
        container = AsyncMock()
        runner = AsyncMock()
        AppLifecycle._task_runner = runner

        await AppLifecycle._on_shutdown(container)

        runner.stop.assert_awaited_once()
        assert AppLifecycle._task_runner is None
