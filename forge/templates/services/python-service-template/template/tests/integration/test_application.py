"""Exercise dependency injection, middleware and the real testing database."""
from fastapi.testclient import TestClient
from app.main import create_app


def test_custom_provider_is_composed_without_patching_runtime():
    from dishka import Provider, Scope, provide

    class Message:
        text = "application extension"

    class Extension(Provider):
        @provide(scope=Scope.APP)
        def message(self) -> Message:
            return Message()

    app = create_app(providers=[Extension()])

    @app.get("/custom-message")
    async def custom_message():
        message = await app.state.dishka_container.get(Message)
        return {"message": message.text}

    with TestClient(app) as client:
        assert client.get("/custom-message").json() == {"message": "application extension"}


def test_readiness_uses_database():
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "UP"


def test_unknown_route_is_not_success():
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/does-not-exist").status_code == 404


def test_item_lifecycle_in_real_database():
    with TestClient(create_app()) as client:
        created = client.post("/api/v1/items", json={"name": "Lifecycle item", "tags": ["integration"]})
        assert created.status_code == 201, created.text
        identity = created.json()["id"]
        url = f"/api/v1/items/{identity}"
        assert client.get(url).json()["name"] == "Lifecycle item"
        updated = client.patch(url, json={"name": "Updated", "status": "ACTIVE"})
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "Updated"
        listed = client.get("/api/v1/items", params={"search": "Updated"})
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert client.post("/api/v1/items", json={"name": "Updated"}).status_code == 409
        assert client.delete(url).status_code == 204
        assert client.get(url).status_code == 404
        assert client.patch(url, json={"name": "gone"}).status_code == 404
        assert client.delete(url).status_code == 404
        assert client.post("/api/v1/items", json={"name": ""}).status_code == 422
