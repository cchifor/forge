"""Phase B1 — ``database.mode=none`` scenario tests.

Exercises the database-layer discriminator. ``database.mode=none``
strips the postgres container + per-backend migrate sidecars from
``docker-compose.yml`` — suitable for stateless services or projects
whose persistence lives outside the generated stack.

Phase B1 scope is **compose-level only**: the Python service template
still scaffolds alembic + SQLAlchemy. A follow-up ``database_strip``
fragment will remove those files too (tracked separately). The B1
validation rejects DB-backed options (``conversation.persistence``,
``rag.backend != none``, etc.) so users can't generate a broken
combination.
"""

from __future__ import annotations

import pytest
import yaml

from forge.config import (
    BackendConfig,
    FrontendConfig,
    FrontendFramework,
    ProjectConfig,
)
from forge.docker_manager import render_compose


def _stateless_config(**options_overrides: object) -> ProjectConfig:
    """Return a Python backend + Vue frontend with ``database.mode=none``."""
    bc = BackendConfig(
        project_name="Stateless",
        name="api",
        features=["events"],
        server_port=5000,
    )
    fc = FrontendConfig(
        framework=FrontendFramework.VUE,
        project_name="Stateless",
        features=["events"],
        server_port=5173,
        include_auth=False,
        include_openapi=False,
        keycloak_url="http://localhost:8080",
        keycloak_realm="master",
        keycloak_client_id="stateless",
    )
    options: dict[str, object] = {"database.mode": "none"}
    options.update(options_overrides)
    return ProjectConfig(
        project_name="Stateless",
        backends=[bc],
        frontend=fc,
        options=options,
    )


# -- Config validation -------------------------------------------------------


class TestDatabaseModeValidation:
    def test_stateless_backend_validates(self):
        config = _stateless_config()
        config.validate()
        assert config.database_mode == "none"

    def test_default_mode_is_generate(self):
        bc = BackendConfig(project_name="default", server_port=5000)
        config = ProjectConfig(project_name="Default", backends=[bc])
        config.validate()
        assert config.database_mode == "generate"

    @pytest.mark.parametrize(
        ("option_key", "option_value", "error_fragment"),
        [
            ("conversation.persistence", True, "conversation.persistence"),
            ("rag.backend", "qdrant", "rag.backend"),
            ("chat.attachments", True, "chat.attachments"),
            ("agent.streaming", True, "agent.streaming"),
            ("agent.llm", True, "agent.llm"),
            ("platform.admin", True, "platform.admin"),
            ("platform.webhooks", True, "platform.webhooks"),
        ],
    )
    def test_mode_none_rejects_db_backed_options(
        self, option_key, option_value, error_fragment
    ):
        config = _stateless_config(**{option_key: option_value})
        with pytest.raises(ValueError, match=error_fragment):
            config.validate()

    def test_mode_none_lists_all_conflicts(self):
        """The error names every conflicting option in one shot so the
        user can fix them together rather than re-running the generator."""
        config = _stateless_config(
            **{"conversation.persistence": True, "platform.admin": True}
        )
        with pytest.raises(ValueError) as exc:
            config.validate()
        msg = str(exc.value)
        assert "conversation.persistence" in msg
        assert "platform.admin" in msg

    def test_rag_backend_none_is_fine(self):
        """``rag.backend=none`` is the default; stateless mode shouldn't
        reject it."""
        config = _stateless_config(**{"rag.backend": "none"})
        config.validate()  # should not raise

    def test_mode_generate_allows_db_backed_options(self):
        """The B1 validator only fires when ``database.mode=none``; the
        default generate mode must stay permissive."""
        config = _stateless_config()
        config.options["database.mode"] = "generate"
        config.options["conversation.persistence"] = True
        # conversation.persistence has its own downstream requirements,
        # but database.mode=generate shouldn't reject it.
        config.validate()


# -- Compose rendering -------------------------------------------------------


class TestStatelessCompose:
    def test_postgres_stripped(self, tmp_path):
        config = _stateless_config()
        config.validate()
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        assert "postgres" not in data["services"]
        assert "pgadmin" not in data["services"]

    def test_migrate_services_stripped(self, tmp_path):
        config = _stateless_config()
        config.validate()
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        assert all(not name.endswith("-migrate") for name in data["services"])

    def test_backend_service_has_no_db_env_vars(self, tmp_path):
        config = _stateless_config()
        config.validate()
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        env = data["services"]["api"]["environment"]
        # The Python backend exposes ENV (pydantic-settings) but not the
        # database URL. node/rust would do likewise.
        assert "APP__DB__URL" not in env
        assert "DATABASE_URL" not in env

    def test_backend_service_has_no_migrate_dependency(self, tmp_path):
        """Without a migrate sidecar, the backend service shouldn't list
        one in ``depends_on`` — docker-compose rejects unknown service
        references."""
        config = _stateless_config()
        config.validate()
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        depends = data["services"]["api"].get("depends_on") or {}
        assert "api-migrate" not in depends

    def test_volumes_block_absent(self, tmp_path):
        """No postgres → no ``pgdata`` volume. YAML's ``volumes:`` top-level
        key should be absent so docker-compose doesn't complain about an
        empty mapping."""
        config = _stateless_config()
        config.validate()
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        assert not (data.get("volumes") or {})


class TestStatelessKeycloakCoexistence:
    """``database.mode=none + include_keycloak=True`` is tricky: keycloak
    needs postgres for its own state, but backends don't. Postgres must
    still render."""

    def test_postgres_renders_for_keycloak(self, tmp_path):
        config = _stateless_config()
        config.frontend.include_auth = True
        config.frontend.keycloak_client_id = "stateless"
        config.include_keycloak = True
        config.validate()
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        assert "postgres" in data["services"]
        assert "keycloak" in data["services"]

    def test_backend_still_has_no_db_wiring(self, tmp_path):
        """Even with postgres rendered for keycloak, backends stay
        stateless — no APP__DB__URL / DATABASE_URL env vars."""
        config = _stateless_config()
        config.frontend.include_auth = True
        config.frontend.keycloak_client_id = "stateless"
        config.include_keycloak = True
        config.validate()
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        env = data["services"]["api"]["environment"]
        assert "APP__DB__URL" not in env
        # But auth env vars DO populate since keycloak is enabled.
        assert env["APP__SECURITY__AUTH__ENABLED"] == "true"


# -- Backward compatibility --------------------------------------------------


class TestDefaultMode:
    """``database.mode=generate`` (default) must preserve pre-B1 behavior."""

    def test_postgres_still_renders(self, tmp_path):
        bc = BackendConfig(project_name="x", name="api", server_port=5000)
        config = ProjectConfig(project_name="X", backends=[bc])
        config.validate()
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        assert "postgres" in data["services"]

    def test_migrate_service_still_renders(self, tmp_path):
        bc = BackendConfig(project_name="x", name="api", server_port=5000)
        config = ProjectConfig(project_name="X", backends=[bc])
        config.validate()
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        assert "api-migrate" in data["services"]

    def test_backend_has_db_env_var(self, tmp_path):
        bc = BackendConfig(project_name="x", name="api", server_port=5000)
        config = ProjectConfig(project_name="X", backends=[bc])
        config.validate()
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        env = data["services"]["api"]["environment"]
        assert "APP__DB__URL" in env
