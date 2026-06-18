"""Regression: shared_rls covers every tenant-scoped feature table (audit #3).

``multitenancy_rls`` shipped a single ``0002_enable_rls.py`` whose
``RLS_TABLES`` was hard-coded to ``("items", "audit_logs")``. Feature
fragments (conversation, file_upload, rag, webhooks) add models that subclass
``TenantMixin`` (so they carry ``customer_id``) but shipped NO companion RLS
migration, and nothing auto-extended ``RLS_TABLES``. Under
``database.multitenancy=shared_rls`` the DB-enforced isolation backstop
therefore silently did not apply to those tables — any query omitting the
``customer_id`` predicate (raw ``text()``, a new endpoint, an aggregate, a
relationship load) leaks cross-tenant there, while the same mistake on
``items``/``audit_logs`` is caught by RLS.

This scans every feature model that declares ``TenantMixin`` and asserts each
table is covered by an RLS migration in the multitenancy_rls fragment — a
drift guard that fails the moment a new tenant-scoped feature table ships
without RLS coverage.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_FEATURES = Path(__file__).resolve().parent.parent / "forge" / "features"
_RLS_VERSIONS = (
    _FEATURES
    / "multitenancy/templates/multitenancy_rls_python/python/files/alembic/versions"
)


def _tenant_feature_tables() -> set[str]:
    """Every ``__tablename__`` on a feature model subclassing ``TenantMixin``."""
    tables: set[str] = set()
    for model in _FEATURES.rglob("*.py"):
        if "/models/" not in model.as_posix():
            continue
        text = model.read_text(encoding="utf-8")
        if "TenantMixin" not in text:
            continue
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ClassDef) and any(
                isinstance(b, ast.Name) and b.id == "TenantMixin" for b in node.bases
            ):
                for stmt in node.body:
                    if (
                        isinstance(stmt, ast.Assign)
                        and isinstance(stmt.value, ast.Constant)
                        and any(
                            isinstance(t, ast.Name) and t.id == "__tablename__"
                            for t in stmt.targets
                        )
                    ):
                        tables.add(stmt.value.value)
    return tables


def _rls_covered_tables() -> set[str]:
    """Table names listed in any ``*_TABLES`` tuple across RLS migrations."""
    covered: set[str] = set()
    for mig in _RLS_VERSIONS.glob("*.py"):
        text = mig.read_text(encoding="utf-8")
        for block in re.finditer(
            r"(?:RLS_TABLES|FEATURE_RLS_TABLES)[^=]*=\s*\(([^)]*)\)", text, re.DOTALL
        ):
            covered.update(re.findall(r'"([a-zA-Z_][a-zA-Z0-9_]*)"', block.group(1)))
    return covered


def test_every_tenant_feature_table_has_rls_coverage() -> None:
    tenant = _tenant_feature_tables()
    assert tenant, "no TenantMixin feature tables discovered — scan is broken"
    covered = _rls_covered_tables()
    missing = tenant - covered
    assert not missing, (
        "tenant-scoped feature tables lack shared_rls coverage (cross-tenant leak risk): "
        f"{sorted(missing)}"
    )
