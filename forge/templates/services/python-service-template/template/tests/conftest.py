"""Root test fixtures."""

import os
from pathlib import Path

import pytest
import yaml

# Ensure tests use the testing config
os.environ.setdefault("ENV", "testing")


@pytest.fixture
def mock_config_dir(tmp_path: Path):
    """Provide a temporary config directory."""
    return tmp_path


@pytest.fixture
def create_config_file(mock_config_dir: Path):
    """Factory to create YAML config files in the temp dir."""

    def _create(name: str, data: dict) -> Path:
        path = mock_config_dir / name
        path.write_text(yaml.dump(data))
        return path

    return _create
