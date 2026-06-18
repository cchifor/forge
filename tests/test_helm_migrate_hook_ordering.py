"""Regression: Helm config/secret exist before the pre-install migrate Job (audit #6).

On the default external-DB path the per-backend migrate Job is a
``pre-install,pre-upgrade`` hook (weight -5) and pulls all config via
``envFrom`` referencing ``<release>-<name>-config`` (non-optional configMapRef)
and ``<release>-<name>-secret``. Those were main-phase resources (no hook
annotation), created AFTER pre-install hooks — so on a FIRST ``helm install``
neither existed yet: the non-optional configMapRef put the Job pod in
CreateContainerConfigError and blocked the install (hidden on upgrade because
the prior release already created them).

Fix: annotate the per-backend ConfigMap + Secret as ``pre-install,pre-upgrade``
hooks at a MORE-NEGATIVE weight (-10) than the migrate Job (-5) so they exist
first, with ``before-hook-creation`` (not ``hook-succeeded``) so they persist
for the main-phase Deployments that also envFrom them.

NOTE: live ordering can only be confirmed by a real ``helm install`` on a
cluster (kind), which isn't available in this environment — `helm template` /
`helm lint` (test_deploy_helm_validation) validate syntax; the install-time
ordering guarantee is asserted structurally here.
"""

from __future__ import annotations

import re
from pathlib import Path

_HELM = (
    Path(__file__).resolve().parent.parent
    / "forge/features/deploy/templates/deploy_helm_chart/all/files/deploy/helm/templates"
)


def _weights(text: str) -> list[int]:
    return [int(m) for m in re.findall(r'"helm\.sh/hook-weight":\s*"(-?\d+)"', text)]


def test_configmap_and_secret_are_preinstall_hooks_before_migrate() -> None:
    cm = (_HELM / "configmap.yaml").read_text(encoding="utf-8")
    sec = (_HELM / "secret.yaml").read_text(encoding="utf-8")
    jobs = (_HELM / "jobs.yaml").read_text(encoding="utf-8")

    for src, label in ((cm, "configmap.yaml"), (sec, "secret.yaml")):
        assert "pre-install,pre-upgrade" in src, f"{label} must be a pre-install hook"
        assert "before-hook-creation" in src, (
            f"{label} must persist (before-hook-creation, NOT hook-succeeded) for "
            "the main-phase Deployments that envFrom it"
        )
        assert -10 in _weights(src), f"{label} must use hook-weight -10"

    # The migrate Job runs at -5; config/secret at -10 are created strictly
    # before it (Helm runs hooks in ascending weight order).
    assert all(w < -5 for w in _weights(cm)), "configmap weight must precede the migrate Job (-5)"
    assert all(w < -5 for w in _weights(sec)), "secret weight must precede the migrate Job (-5)"
