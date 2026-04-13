"""Integration tests for the Tasks API endpoints."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from service.tasks.registry import task_handler


# Register a test handler so the enqueue endpoint accepts it.
@task_handler("test.echo")
async def _echo_handler(payload: dict) -> dict | None:
    return payload


class TestEnqueueTask:
    async def test_enqueue_returns_201(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/tasks",
            json={
                "task_type": "test.echo",
                "payload": {"msg": "hi"},
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["task_type"] == "test.echo"
        assert data["status"] == "PENDING"
        assert "id" in data

    async def test_enqueue_unknown_type_returns_400(
        self, client: AsyncClient
    ):
        resp = await client.post(
            "/api/v1/tasks",
            json={"task_type": "no.such.type"},
        )
        assert resp.status_code == 400

    async def test_enqueue_missing_type_returns_422(
        self, client: AsyncClient
    ):
        resp = await client.post("/api/v1/tasks", json={})
        assert resp.status_code == 422

    async def test_enqueue_with_retries(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/tasks",
            json={
                "task_type": "test.echo",
                "max_retries": 5,
            },
        )
        assert resp.status_code == 201


class TestGetTask:
    async def test_get_task_found(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/v1/tasks",
            json={"task_type": "test.echo"},
        )
        task_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/tasks/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == task_id
        assert data["task_type"] == "test.echo"
        assert data["status"] == "PENDING"
        assert data["attempts"] == 0

    async def test_get_task_not_found(self, client: AsyncClient):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/tasks/{fake_id}")
        assert resp.status_code == 404


class TestCancelTask:
    async def test_cancel_pending(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/v1/tasks",
            json={"task_type": "test.echo"},
        )
        task_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/v1/tasks/{task_id}")
        assert resp.status_code == 204

    async def test_cancel_already_cancelled(
        self, client: AsyncClient
    ):
        create_resp = await client.post(
            "/api/v1/tasks",
            json={"task_type": "test.echo"},
        )
        task_id = create_resp.json()["id"]

        # First cancel succeeds
        await client.delete(f"/api/v1/tasks/{task_id}")
        # Second cancel conflicts
        resp = await client.delete(f"/api/v1/tasks/{task_id}")
        assert resp.status_code == 409

    async def test_cancel_nonexistent(self, client: AsyncClient):
        fake_id = str(uuid.uuid4())
        resp = await client.delete(f"/api/v1/tasks/{fake_id}")
        assert resp.status_code == 409
