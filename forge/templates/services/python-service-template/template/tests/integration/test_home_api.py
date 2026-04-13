"""Integration tests for home endpoints."""


class TestHomeEndpoints:
    async def test_root(self, client):
        resp = await client.get("/api/v1/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"

    async def test_root_has_status_field(self, client):
        resp = await client.get("/api/v1/")
        data = resp.json()
        assert "status" in data
