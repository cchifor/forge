"""WS-10.1: the ``deploy`` feature emits Kubernetes manifests + a Helm chart.

``deploy.target=kubernetes`` adds per-backend ``k8s/`` manifests, a
project-level HPA, and a Helm chart under ``helm/``. The default
(``none``) emits nothing, so existing projects are unaffected.
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.generator import generate


def _k8s_config(tmp_path: Path, *, target: str = "kubernetes") -> ProjectConfig:
    return ProjectConfig(
        project_name="Deploy Proj",
        backends=[
            BackendConfig(
                project_name="Deploy Proj",
                language=BackendLanguage.PYTHON,
                server_port=8000,
            ),
        ],
        options={"deploy.target": target},
        output_dir=str(tmp_path),
    )


# --- registration ---------------------------------------------------------


def test_deploy_feature_is_discovered():
    from forge import feature_loader as fl

    fl.load_all()
    names = {m.name for m in fl.LOADED_FEATURES}
    assert "deploy" in names


def test_deploy_target_option_registered():
    from forge.options._registry import OPTION_REGISTRY

    opt = OPTION_REGISTRY.get("deploy.target")
    assert opt is not None
    assert set(opt.options) == {"none", "docker-compose", "kubernetes"}
    assert opt.default == "none"


def test_kubernetes_enables_three_fragments():
    from forge.options._registry import OPTION_REGISTRY

    opt = OPTION_REGISTRY["deploy.target"]
    assert set(opt.enables["kubernetes"]) == {
        "deploy_kubernetes",
        "deploy_k8s_hpa",
        "deploy_helm_chart",
    }
    assert opt.enables.get("none", ()) == ()
    assert opt.enables.get("docker-compose", ()) == ()


def test_three_deploy_fragments_registered():
    from forge.fragments import FRAGMENT_REGISTRY

    for name in ("deploy_kubernetes", "deploy_k8s_hpa", "deploy_helm_chart"):
        assert name in FRAGMENT_REGISTRY, name


# --- generation -----------------------------------------------------------


def test_kubernetes_target_emits_manifests(tmp_path: Path):
    config = _k8s_config(tmp_path)
    root = generate(config, quiet=True)
    assert root.exists()
    assert list(root.rglob("k8s/deployment.yaml")), "expected a k8s/deployment.yaml"
    assert (root / "helm" / "Chart.yaml").is_file(), "expected helm/Chart.yaml"
    assert (root / "k8s" / "hpa.yaml").is_file(), "expected project-level k8s/hpa.yaml"


def test_helm_go_templates_survive_verbatim(tmp_path: Path):
    config = _k8s_config(tmp_path)
    root = generate(config, quiet=True)
    dep = root / "helm" / "templates" / "deployment.yaml"
    assert dep.is_file()
    text = dep.read_text(encoding="utf-8")
    # Helm Go-template syntax must NOT have been Jinja-rendered/stripped.
    assert "{{ .Values.image.repository }}" in text
    assert '{{ include "app.fullname" . }}' in text


def test_none_target_emits_no_deploy_files(tmp_path: Path):
    config = _k8s_config(tmp_path, target="none")
    root = generate(config, quiet=True)
    assert not (root / "helm").exists()
    assert not list(root.rglob("k8s/deployment.yaml"))
