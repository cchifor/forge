"""The ``deploy`` feature emits a topology-aware Helm umbrella chart.

``deploy.target=kubernetes`` renders a single Helm chart under
``deploy/helm/`` whose ``values.yaml`` is built from the project's deployment
topology — one ``workloads`` entry per backend plus the frontend and
platform-service toggles. The chart's ``templates/*.yaml`` are pure Go and
``range`` over ``.Values.workloads``. The default (``none``) emits nothing, so
existing projects are unaffected.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from forge.config import BackendConfig, BackendLanguage, FrontendConfig, ProjectConfig
from forge.config._frontend import FrontendFramework
from forge.generator import generate


def _k8s_config(*, target: str = "kubernetes", port: int = 8000, **kw) -> ProjectConfig:
    return ProjectConfig(
        project_name="Deploy Proj",
        backends=[BackendConfig(name="api", language=BackendLanguage.PYTHON, server_port=port)],
        options={"deploy.target": target},
        **kw,
    )


def _gen(config: ProjectConfig) -> Path:
    # dry_run skips the per-backend toolchain install (no network needed) and
    # returns the generated project root in a temp dir.
    return generate(config, quiet=True, dry_run=True)


def _values(root: Path) -> dict:
    return yaml.safe_load((root / "deploy" / "helm" / "values.yaml").read_text(encoding="utf-8"))


# --- registration ---------------------------------------------------------


def test_deploy_feature_is_discovered():
    from forge import feature_loader as fl

    fl.load_all()
    assert "deploy" in {m.name for m in fl.LOADED_FEATURES}


def test_deploy_target_option_registered():
    from forge.options._registry import OPTION_REGISTRY

    opt = OPTION_REGISTRY.get("deploy.target")
    assert opt is not None
    assert set(opt.options) == {"none", "docker-compose", "kubernetes"}
    assert opt.default == "none"


def test_kubernetes_enables_only_helm_chart():
    from forge.options._registry import OPTION_REGISTRY

    opt = OPTION_REGISTRY["deploy.target"]
    assert set(opt.enables["kubernetes"]) == {"deploy_helm_chart"}
    assert opt.enables.get("none", ()) == ()
    assert opt.enables.get("docker-compose", ()) == ()


def test_helm_fragment_registered_and_retired_fragments_absent():
    from forge.fragments import FRAGMENT_REGISTRY

    assert "deploy_helm_chart" in FRAGMENT_REGISTRY
    # The static per-backend raw-k8s + placeholder-HPA fragments were retired in
    # favour of the topology-aware chart (deploy/k8s is now helm-template-derived).
    assert "deploy_kubernetes" not in FRAGMENT_REGISTRY
    assert "deploy_k8s_hpa" not in FRAGMENT_REGISTRY


# --- generation -----------------------------------------------------------


def test_kubernetes_target_emits_topology_chart():
    root = _gen(_k8s_config())
    helm = root / "deploy" / "helm"
    assert (helm / "Chart.yaml").is_file()
    assert (helm / "values.yaml").is_file()
    assert (helm / "templates" / "deployments.yaml").is_file()
    # The chart lands under deploy/, not the old project-root helm/.
    assert not (root / "helm").exists()
    # values.yaml carries a per-backend workload entry built from topology.
    assert "api" in _values(root)["workloads"]


def test_helm_go_templates_survive_verbatim():
    """The chart bodies are pure Go-templates copied verbatim — Jinja must not
    have rendered/stripped the ``{{ .Values.* }}`` / ``range`` syntax."""
    root = _gen(_k8s_config())
    text = (root / "deploy" / "helm" / "templates" / "deployments.yaml").read_text(encoding="utf-8")
    assert "range $name, $w := .Values.workloads" in text
    assert "{{ $w.image.repository }}" in text
    assert 'include "app.labels" $' in text


def test_none_target_emits_no_deploy_chart():
    root = _gen(_k8s_config(target="none"))
    assert not (root / "deploy" / "helm").exists()


def test_workload_port_tracks_server_port():
    """A workload's containerPort follows the backend's configured server_port
    (regression for the old static-8000 mismatch)."""
    root = _gen(_k8s_config(port=8137))
    api = _values(root)["workloads"]["api"]
    assert api["containerPort"] == 8137
    assert api["language"] == "python"
    assert api["env"]["APP__SERVER__PORT"] == "8137"


def test_multi_backend_emits_one_workload_each():
    config = ProjectConfig(
        project_name="Multi",
        backends=[
            BackendConfig(name="user-api", language=BackendLanguage.PYTHON, server_port=8001),
            BackendConfig(name="billing", language=BackendLanguage.NODE, server_port=8002),
        ],
        frontend=FrontendConfig(framework=FrontendFramework.VUE, project_name="Multi"),
        options={"deploy.target": "kubernetes"},
    )
    workloads = _values(_gen(config))["workloads"]
    assert set(workloads) == {"user-api", "billing"}
    assert workloads["user-api"]["containerPort"] == 8001
    assert workloads["billing"]["containerPort"] == 8002
    # The frontend Deployment is enabled because the project has a frontend.
    assert _values(_gen(config))["frontend"]["enabled"] is True


def test_secret_env_is_placeholder_not_hardcoded():
    """forge must NOT bake a real or deterministic credential into the chart —
    secretEnv carries CHANGEME placeholders the user overrides at deploy time."""
    api = _values(_gen(_k8s_config()))["workloads"]["api"]
    db_url = api["secretEnv"]["APP__DB__URL"]
    assert "CHANGEME" in db_url


def _keycloak_k8s_config() -> ProjectConfig:
    # Gatekeeper binds host port 5000 when keycloak is enabled, so the backend
    # must avoid it (the validator reserves 5000). Use 5010.
    return ProjectConfig(
        project_name="Deploy KC",
        backends=[BackendConfig(name="api", language=BackendLanguage.PYTHON, server_port=5010)],
        frontend=FrontendConfig(framework=FrontendFramework.VUE, project_name="Deploy KC"),
        include_keycloak=True,
        keycloak_port=18080,
        options={"deploy.target": "kubernetes"},
    )


def _infra_yaml(root: Path) -> str:
    return (root / "deploy" / "helm" / "templates" / "infra.yaml").read_text(encoding="utf-8")


# --- E1: in-cluster Service names are stable literals matching the DB host ----


def test_postgres_service_name_is_literal_matching_db_host():
    """The in-cluster Postgres Service must render to the bare literal ``postgres``
    (values.yaml has no access to .Release.Name), so the migrate hook + pods can
    resolve the DB host hardcoded in each workload's secretEnv."""
    root = _gen(_keycloak_k8s_config())
    infra = _infra_yaml(root)

    # Find the `kind: Service` block whose name label is `postgres`.
    svc_blocks = [b for b in infra.split("---") if "kind: Service" in b]
    pg_blocks = [b for b in svc_blocks if "app.kubernetes.io/name: postgres" in b]
    assert pg_blocks, "no postgres Service block found in infra.yaml"
    pg = pg_blocks[0]

    m = re.search(r"^metadata:\n  name:\s*(\S+)", pg, re.MULTILINE)
    assert m, f"could not parse metadata.name from postgres Service block:\n{pg}"
    pg_svc_name = m.group(1)
    assert "{{" not in pg_svc_name, (
        f"postgres Service name is a Helm expr, not a literal: {pg_svc_name!r}"
    )
    assert pg_svc_name == "postgres"

    # The literal Service name must match the bare host in a workload's DB URL.
    api = _values(root)["workloads"]["api"]
    db_url = api["secretEnv"]["APP__DB__URL"]
    host = db_url.split("@", 1)[1].split(":", 1)[0]
    assert host == pg_svc_name == "postgres"


# --- E2: keycloak projects carry auth env into the Helm chart -----------------


def test_keycloak_helm_workload_env_carries_auth():
    """A keycloak k8s deploy must turn auth ON in-cluster — the workload env
    block mirrors the compose auth env (enabled/server/realm/client/issuer/aud)."""
    root = _gen(_keycloak_k8s_config())
    env = _values(root)["workloads"]["api"]["env"]
    assert env["APP__SECURITY__AUTH__ENABLED"] == "true"
    assert env["APP__SECURITY__AUTH__SERVER_URL"] == "http://keycloak:8080"
    assert "APP__SECURITY__AUTH__REALM" in env
    assert "APP__SECURITY__AUTH__CLIENT_ID" in env
    assert env["GATEKEEPER_ISSUER"] == "http://gatekeeper:5000"
    assert env["SERVICE_AUDIENCE"] == "forge-services"


def test_non_keycloak_helm_workload_env_has_no_auth():
    """A non-keycloak project must not gain any auth env (byte-identical path)."""
    env = _values(_gen(_k8s_config()))["workloads"]["api"]["env"]
    assert "APP__SECURITY__AUTH__ENABLED" not in env
    assert "GATEKEEPER_ISSUER" not in env
    assert "SERVICE_AUDIENCE" not in env
