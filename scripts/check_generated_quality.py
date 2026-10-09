"""Render, install and enforce real native gates for a reference application."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from forge.config import (
    BackendConfig,
    BackendLanguage,
    FrontendConfig,
    FrontendFramework,
    ProjectConfig,
)
from forge.generator import generate
from forge.quality.architecture import verify_architecture
from forge.quality.coverage import evaluate
from forge.quality.dependencies import dependencies
from forge.quality.model import subjects
from forge.quality.runner import run_suites


def check(language: str, destination: Path) -> dict:
    frontend = language in {"vue", "svelte"}
    config = ProjectConfig(
        project_name=f"quality-{language}",
        backends=[
            BackendConfig(
                name="api",
                language=BackendLanguage.PYTHON if frontend else BackendLanguage(language),
            )
        ],
        frontend=FrontendConfig(
            project_name="frontend",
            framework=FrontendFramework(language),
            include_auth=False,
            include_chat=False,
            include_openapi=False,
        )
        if frontend
        else None,
    )
    rendered = generate(config, quiet=True, dry_run=True)
    try:
        shutil.copytree(rendered, destination)
    finally:
        shutil.rmtree(rendered.parent)
    architecture = verify_architecture(destination)
    if not architecture["passed"]:
        raise ValueError(json.dumps(architecture))
    dependencies(destination, lock=True)
    dependencies(destination)
    run_suites(destination, subject=config.frontend_slug if frontend else None)
    reports = [
        json.loads(path.read_text()) for path in (destination / ".forge/coverage").glob("*/*.json")
    ]
    inventory = subjects(config, destination)
    if frontend:
        inventory = [item for item in inventory if item["language"] == language]
    result = evaluate(destination, reports, inventory)
    result["architecture"] = architecture
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--language", choices=["python", "node", "rust", "vue", "svelte"], required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = check(args.language, args.output.resolve())
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 12)
