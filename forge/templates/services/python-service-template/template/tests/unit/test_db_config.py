"""Tests for service.db.config."""

from service.db.config import build_engine_args, obfuscate_url


class TestBuildEngineArgs:
    def test_sqlite_url(self):
        args = build_engine_args(
            url="sqlite+aiosqlite:///test.db",
            pool_size=5, max_overflow=10, pool_timeout=30,
            pool_recycle=3600, echo=False, application_name=None,
            ssl_mode=None, connect_args=None,
        )
        assert args["connect_args"]["check_same_thread"] is False
        assert "pool_size" not in args

    def test_postgres_url(self):
        args = build_engine_args(
            url="postgresql+asyncpg://user:pass@host/db",
            pool_size=5, max_overflow=10, pool_timeout=30,
            pool_recycle=3600, echo=True, application_name=None,
            ssl_mode=None, connect_args=None,
        )
        assert args["pool_size"] == 5
        assert args["max_overflow"] == 10
        assert args["pool_timeout"] == 30
        assert args["echo"] is True

    def test_application_name_asyncpg(self):
        args = build_engine_args(
            url="postgresql+asyncpg://host/db",
            pool_size=5, max_overflow=10, pool_timeout=30,
            pool_recycle=3600, echo=False, application_name="myapp",
            ssl_mode=None, connect_args=None, is_async=True,
        )
        assert args["connect_args"]["server_settings"]["application_name"] == "myapp"

    def test_application_name_sync(self):
        args = build_engine_args(
            url="postgresql://host/db",
            pool_size=5, max_overflow=10, pool_timeout=30,
            pool_recycle=3600, echo=False, application_name="myapp",
            ssl_mode=None, connect_args=None, is_async=False,
        )
        assert args["connect_args"]["application_name"] == "myapp"

    def test_ssl_mode_async(self):
        args = build_engine_args(
            url="postgresql+asyncpg://host/db",
            pool_size=5, max_overflow=10, pool_timeout=30,
            pool_recycle=3600, echo=False, application_name=None,
            ssl_mode="require", connect_args=None, is_async=True,
        )
        assert args["connect_args"]["ssl"] == "require"

    def test_ssl_mode_sync(self):
        args = build_engine_args(
            url="postgresql://host/db",
            pool_size=5, max_overflow=10, pool_timeout=30,
            pool_recycle=3600, echo=False, application_name=None,
            ssl_mode="require", connect_args=None, is_async=False,
        )
        assert args["connect_args"]["sslmode"] == "require"

    def test_json_serializer_set(self):
        args = build_engine_args(
            url="sqlite:///test.db",
            pool_size=5, max_overflow=10, pool_timeout=30,
            pool_recycle=3600, echo=False, application_name=None,
            ssl_mode=None, connect_args=None,
        )
        assert "json_serializer" in args
        assert "json_deserializer" in args


class TestObfuscateUrl:
    def test_with_credentials(self):
        assert obfuscate_url("postgresql://user:pass@host/db") == "...@host/db"

    def test_without_credentials(self):
        assert obfuscate_url("sqlite:///test.db") == "sqlite:///test.db"
