"""Optional API keys require a real Gatekeeper and propagate to deployment."""

import json
from pathlib import Path

import pytest
import yaml

from forge.capability_resolver import resolve
from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.errors import OptionsError
from forge.generator import generate


def _config(**kwargs):
    return ProjectConfig(
        project_name="keys",
        backends=[BackendConfig(name="orders", language=BackendLanguage.PYTHON, server_port=5020)],
        **kwargs,
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_api_key_option_sets_gatekeeper_environment(tmp_path: Path, enabled):
    config = _config(include_keycloak=True, options={"auth.api_keys": enabled})
    config.validate()
    root = generate(config, quiet=True, dry_run=True)
    path = root / "docker-compose.yml"
    env = yaml.safe_load(path.read_text())["services"]["gatekeeper"]["environment"]
    assert env["API_KEYS_ENABLED"] == str(enabled).lower()
    realm = json.loads((root / "deploy/infra/keycloak-realm.json").read_text())["realm"]
    services = yaml.safe_load(path.read_text())["services"]
    assert realm == env["KEYCLOAK_ADMIN_REALM"] == "app"
    assert services["keycloak-realm-sync"]["environment"]["KEYCLOAK_ADMIN_REALM"] == realm
    labels = yaml.safe_load(path.read_text())["services"]["orders"]["labels"]
    assert any(label.endswith("-rewrite,auth,strip-api-key") for label in labels)


def test_api_keys_disabled_by_default():
    assert resolve(_config(include_keycloak=True)).option_values["auth.api_keys"] is False


@pytest.mark.parametrize(
    "include,options",
    [
        (False, {}),
        (True, {"auth.mode": "none"}),
        (False, {"auth.provider": "in_memory"}),
        (True, {"auth.provider": "oidc_generic"}),
    ],
)
def test_api_keys_without_gatekeeper_rejected(include, options):
    config = _config(include_keycloak=include, options={"auth.api_keys": True, **options})
    with pytest.raises(OptionsError, match="auth.api_keys requires"):
        resolve(config)
