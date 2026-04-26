"""Codemod: move hand-written domain entities to ``domain/*.yaml`` DSL.

1.0.0a1 introduces a YAML-driven entity DSL under ``domain/`` that
emits per-language models + OpenAPI components. Pre-1.0 projects have
hand-written models in each service's ``src/app/domain/*.py`` /
``src/schemas/*.ts`` / etc.

This codemod does NOT automatically rewrite those files — the mapping
from user-customized Python code to YAML is lossy and a mechanical
codemod would risk silently dropping constraints. Instead, it:

  1. Detects existing hand-written entity files.
  2. Emits a ``domain/<snake>.yaml.suggested`` skeleton alongside each,
     derived from the entity name alone (no field reflection).
  3. Prints a guidance block instructing the user to fill in fields.

Users who want the YAML-driven path rename the ``.suggested`` file and
hand-fill its fields, then delete the legacy Python/TS file. Users who
prefer hand-written models leave everything untouched.
"""

from __future__ import annotations

from pathlib import Path

from forge.migrations.base import MigrationReport

NAME = "entities"
FROM = "0.x"
TO = "1.0.0a1"
DESCRIPTION = "Suggest domain/*.yaml stubs alongside hand-written entity files."

_YAML_TEMPLATE = """\
name: {name}
plural: {plural}
description: {name} — CRUD entity (filled in by `forge migrate-entities`).
fields:
  - name: id
    type: uuid
    primary_key: true
  # Add this entity's remaining fields below (delete the example fields you don't need).
  - name: customer_id
    type: uuid
  - name: user_id
    type: uuid
  - name: created_at
    type: datetime
  - name: updated_at
    type: datetime
indices:
  - [customer_id, name]
"""


def run(project_root: Path, dry_run: bool = False, quiet: bool = False) -> MigrationReport:
    report = MigrationReport(name=NAME, applied=False)

    domain_dir = project_root / "domain"
    if not dry_run:
        domain_dir.mkdir(exist_ok=True)

    # Naive heuristic: look for Python `app/domain/*.py` files (one per
    # entity in the reference layout).
    entity_dirs = list(project_root.glob("services/*/src/app/domain"))
    for entity_dir in entity_dirs:
        for py in entity_dir.glob("*.py"):
            if py.stem in ("__init__", "enums"):
                continue
            pascal = _to_pascal(py.stem)
            plural = _plural(py.stem)
            target = domain_dir / f"{py.stem}.yaml.suggested"
            if target.exists():
                continue
            body = _YAML_TEMPLATE.format(name=pascal, plural=plural)
            if dry_run:
                report.changes.append(
                    f"would suggest: domain/{py.stem}.yaml.suggested (from {py.relative_to(project_root)})"
                )
            else:
                target.write_text(body, encoding="utf-8")
                report.changes.append(
                    f"suggested: domain/{py.stem}.yaml.suggested — fill in fields then rename to .yaml"
                )

    if not report.changes:
        report.skipped_reason = "no domain entity files detected"
    else:
        report.applied = not dry_run
    return report


def _to_pascal(snake: str) -> str:
    return "".join(part.capitalize() for part in snake.split("_") if part)


def _plural(snake: str) -> str:
    if snake.endswith("y") and len(snake) > 1 and snake[-2] not in "aeiou":
        return snake[:-1] + "ies"
    if snake.endswith(("s", "x", "z", "ch", "sh")):
        return snake + "es"
    return snake + "s"
