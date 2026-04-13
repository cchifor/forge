"""Integration tests for admin endpoints."""

import logging


class TestAdminLogLevel:
    async def test_set_valid_level(self, client):
        resp = await client.post(
            "/api/v1/admin/log-level",
            json={"level": "DEBUG"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_level"] == "DEBUG"

    async def test_set_valid_level_warning(self, client):
        resp = await client.post(
            "/api/v1/admin/log-level",
            json={"level": "WARNING"},
        )
        assert resp.status_code == 200
        assert resp.json()["current_level"] == "WARNING"
