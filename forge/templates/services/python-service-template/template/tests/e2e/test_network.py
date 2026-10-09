"""Real HTTP requests to the instrumented application with startup/shutdown."""
import socket
import threading
import time
import httpx
import uvicorn
from app.main import create_app


def test_live_server():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(), log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started, "Application startup failed"
            response = httpx.get(f"http://127.0.0.1:{port}/api/v1/health/live", timeout=5)
            assert response.status_code == 200
            assert response.json()["status"] == "UP"
            assert httpx.get(f"http://127.0.0.1:{port}/not-found", timeout=5).status_code == 404
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Application shutdown timed out"
