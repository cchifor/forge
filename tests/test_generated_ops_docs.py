"""#258 — every generated backend ships operator + observability docs.

Only ``tenant-management-service`` shipped a ``HARDENING.md``; the python /
node / rust base service templates shipped no operator runbook. This pins
that each base template emits an ``OPERATIONS.md`` (config order, migrations /
advisory-lock, graceful shutdown) and an ``OBSERVABILITY.md`` (otel /
json-logging env vars, RED metrics, Prometheus/Grafana) into the generated
service so the docs can't silently regress out of the templates.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.generator import generate

_BACKENDS = {
    "python": BackendLanguage.PYTHON,
    "node": BackendLanguage.NODE,
    "rust": BackendLanguage.RUST,
}


def _generate(language: BackendLanguage) -> Path:
    bc = BackendConfig(
        name="api",
        project_name="OpsDocs",
        language=language,
        features=["items"],
        server_port=5000,
    )
    cfg = ProjectConfig(
        project_name="OpsDocs",
        backends=[bc],
        # NB: default (DB-backed) mode — database.mode=none is Python-only now
        # (a Node/Rust stateless stack has no stripper), and this test only
        # cares that operator docs ship for every language.
        options={},
    )
    cfg.validate()
    return Path(generate(cfg, quiet=True, dry_run=True)) / "services" / "api"


@pytest.mark.parametrize("language", sorted(_BACKENDS))
@pytest.mark.parametrize("doc", ["OPERATIONS.md", "OBSERVABILITY.md"])
def test_base_template_ships_operator_docs(language: str, doc: str) -> None:
    svc = _generate(_BACKENDS[language])
    target = svc / doc
    assert target.is_file(), f"{language} service is missing {doc}"
    body = target.read_text(encoding="utf-8")
    # Non-trivial content, not a stub.
    assert len(body) > 400, f"{language} {doc} looks like a stub ({len(body)} bytes)"
    # Copier must not have left an unrendered template marker behind.
    assert "{{" not in body and "{%" not in body, f"{language} {doc} has raw Jinja"
