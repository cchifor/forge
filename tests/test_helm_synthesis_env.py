"""Regression: Helm values carry per-backend S2S synthesis env (audit #5).

docker-compose.yml.j2 loops ``be.synthesis_env`` (GATEKEEPER_CLIENT_*,
INTERNAL_SERVICE_URL_*, APP__EVENTS__BUS_URL) per backend, but the Helm
values.yaml.jinja hard-coded only language/auth env and never iterated it —
AND both Helm topology callers (generator + updater) called ``compute_topology``
WITHOUT ``synthesis=``, so ``backend_topology_entry`` set ``synthesis_env={}``.
Net: a kubernetes-target multi-service project emitted S2S env in compose but
NONE in deploy/helm/values.yaml, so Helm-deployed backends failed inter-service
auth/calls at runtime.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_VALUES = (
    _ROOT
    / "forge/features/deploy/templates/deploy_helm_chart/all/files/deploy/helm/values.yaml.jinja"
)
_GENERATOR = _ROOT / "forge/generator.py"
_UPDATER = _ROOT / "forge/sync/forge_to_project/updater/__init__.py"


def test_helm_values_iterate_synthesis_env() -> None:
    jinja = _VALUES.read_text(encoding="utf-8")
    assert "be.synthesis_env" in jinja, (
        "Helm values.yaml.jinja must loop per-backend synthesis_env so S2S env "
        "reaches Helm-deployed backends (parity with docker-compose)"
    )


def test_both_helm_topology_callers_forward_synthesis() -> None:
    gen = _GENERATOR.read_text(encoding="utf-8")
    upd = _UPDATER.read_text(encoding="utf-8")
    assert "synthesis=synthesis)" in gen, (
        "generator must forward synthesis= to compute_topology for the Helm chart"
    )
    assert "synthesis=_synthesis)" in upd, (
        "updater must forward synthesis= to compute_topology so --update keeps S2S env"
    )
