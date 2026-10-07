"""Canonical Python output shared by previews, generation and integrity checks."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from forge.config import ProjectConfig
from forge.injectors.sentinels import _read_block_body
from forge.quality.model import digest
from forge.sync.merge import MergeBlockCollector, sha256_of_text
from forge.sync.provenance import ProvenanceCollector


def canonicalize(config: ProjectConfig, root: Path, collector: ProvenanceCollector) -> None:
    for service in config.backends:
        directory = root / "services" / service.name
        if service.language.value != "python" or not directory.is_dir():
            continue
        targets = [
            str(directory / name) for name in ("src", "tests") if (directory / name).is_dir()
        ]
        if not targets:
            continue
        for path in (directory / "src").rglob("*.py"):
            content = path.read_text()
            if "FORGE:BEGIN" in content and "# isort: skip_file" not in content:
                # Import sorters move sentinel comments independently of their
                # imports, corrupting the existing fragment update protocol.
                path.write_text("# isort: skip_file\n" + content)
        for argv in (["check", "--select", "I,F401", "--fix"], ["format"]):
            subprocess.run(
                [sys.executable, "-m", "ruff", *argv, *targets],
                cwd=directory,
                check=True,
                capture_output=True,
                text=True,
            )
    # Preserve ownership/origin while refreshing content changed by canonicalization.
    for relative, record in collector.records.items():
        path = root / relative
        if path.is_file():
            collector.records[relative] = replace(record, sha256=digest(path))
    for key, record in collector.merge_blocks.items():
        parsed = MergeBlockCollector.parse_key(key)
        if parsed is None:
            continue
        relative, feature, marker = parsed
        body = _read_block_body(root / relative, feature, marker)
        if body is not None:
            collector.merge_blocks[key] = replace(record, sha256=sha256_of_text(body))
