"""Integration tests for health endpoints."""


class TestHealthEndpoints:
    async def test_liveness(self, client):
        resp = await client.get("/api/v1/health/live")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "UP"

    async def test_readiness(self, client):
        resp = await client.get("/api/v1/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("UP", "DOWN")
        assert "components" in data
