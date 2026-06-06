"""Contract tests for the forge-core Eureka discovery wrapper.

``py-eureka-client`` is an optional dependency forge-core does not declare,
so these tests never import it: they stub the lazily-imported module so the
wrapper's delegation contract is verified without the client installed, and
they assert the clear error raised when discovery is used without it.
"""

from __future__ import annotations

import sys
import types

import pytest

import forge_core.discovery as discovery_mod
from forge_core.discovery import Discovery


def _make_discovery() -> Discovery:
    return Discovery(
        app_name="svc",
        service_url="http://eureka:8761/eureka",
        service_port=5000,
        service_user="u",
        service_password="p",
        instance_ip="10.0.0.1",
        instance_host="svc-host",
        instance_port=5000,
    )


class _FakeEureka:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def init(self, **kwargs: object) -> None:
        self.calls.append(("init", kwargs))

    def stop(self) -> None:
        self.calls.append(("stop", {}))

    async def init_async(self, **kwargs: object) -> None:
        self.calls.append(("init_async", kwargs))

    async def stop_async(self) -> None:
        self.calls.append(("stop_async", {}))


@pytest.fixture
def fake_eureka(monkeypatch: pytest.MonkeyPatch) -> _FakeEureka:
    fake = _FakeEureka()
    monkeypatch.setattr(discovery_mod, "_eureka_client", lambda: fake)
    return fake


class TestConstruction:
    def test_stores_all_instance_attributes(self) -> None:
        d = _make_discovery()
        assert d.app_name == "svc"
        assert d.instance_host == "svc-host"
        assert d.instance_port == 5000

    def test_accepts_and_ignores_extra_kwargs(self) -> None:
        d = Discovery(
            app_name="svc",
            service_url="u",
            service_port=1,
            service_user="",
            service_password="",
            instance_ip="",
            instance_host="",
            instance_port=1,
            extra="ignored",
        )
        assert not hasattr(d, "extra")

    def test_str_summarizes_identity(self) -> None:
        text = str(_make_discovery())
        assert "app_name=svc" in text
        assert "instance_host=svc-host" in text


class TestSyncDelegation:
    def test_register_delegates_to_init(self, fake_eureka: _FakeEureka) -> None:
        _make_discovery().register()
        name, kwargs = fake_eureka.calls[0]
        assert name == "init"
        assert kwargs["app_name"] == "svc"
        assert kwargs["eureka_server"] == "http://eureka:8761/eureka"
        assert kwargs["instance_port"] == 5000

    def test_unregister_delegates_to_stop(self, fake_eureka: _FakeEureka) -> None:
        _make_discovery().unregister()
        assert fake_eureka.calls == [("stop", {})]


class TestAsyncDelegation:
    async def test_register_async_schedules_init_async(self, fake_eureka: _FakeEureka) -> None:
        import asyncio

        await _make_discovery().register_async()
        # register_async fires init_async as a background task; let it run.
        await asyncio.sleep(0)
        names = [name for name, _ in fake_eureka.calls]
        assert "init_async" in names

    async def test_unregister_async_awaits_stop_async(self, fake_eureka: _FakeEureka) -> None:
        await _make_discovery().unregister_async()
        assert fake_eureka.calls == [("stop_async", {})]


class TestLazyImport:
    def test_present_module_is_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub = types.ModuleType("py_eureka_client.eureka_client")
        pkg = types.ModuleType("py_eureka_client")
        monkeypatch.setitem(sys.modules, "py_eureka_client", pkg)
        monkeypatch.setitem(sys.modules, "py_eureka_client.eureka_client", stub)
        assert discovery_mod._eureka_client() is stub

    def test_missing_module_raises_clear_runtime_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(name: str) -> object:
            raise ModuleNotFoundError(f"No module named {name!r}")

        monkeypatch.setattr(discovery_mod.importlib, "import_module", _raise)
        with pytest.raises(RuntimeError, match="py-eureka-client"):
            discovery_mod._eureka_client()
