import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource


def resolve_config_references(data: dict[str, Any]) -> dict[str, Any]:
    """
    Resolve ${path} references in configuration data.

    Examples:
        ${db.url} -> "sqlite+aiosqlite:///development.db"
        "http://${host}:${port}" -> "http://localhost:8080"
    """
    pattern = re.compile(r"\$\{([^}]+)\}")
    resolved = deepcopy(data)

    def resolve_path(path: str, visited_paths: list[str]) -> Any:
        if path in visited_paths:
            cycle = " -> ".join(visited_paths + [path])
            raise ValueError(f"Circular reference detected: {cycle}")

        parts = path.split(".")
        value = resolved

        try:
            for part in parts:
                if isinstance(value, dict):
                    value = value[part]
                else:
                    raise KeyError(f"Cannot access '{part}' on non-dict value")
        except KeyError as e:
            raise ValueError(
                f"Configuration reference '${{{path}}}' failed: path not found. "
                f"Available keys at this level: {list(value.keys()) if isinstance(value, dict) else 'N/A'}"
            ) from e

        new_visited = visited_paths + [path]
        return resolve_value(value, new_visited)

    def resolve_value(obj: Any, visited_paths: list[str]) -> Any:
        if isinstance(obj, str):
            match = pattern.fullmatch(obj)
            if match:
                path = match.group(1)
                return resolve_path(path, visited_paths)

            def replace_ref(m):
                path = m.group(1)
                resolved_value = resolve_path(path, visited_paths)
                return str(resolved_value)

            if pattern.search(obj):
                return pattern.sub(replace_ref, obj)

        elif isinstance(obj, dict):
            return {k: resolve_value(v, visited_paths) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [resolve_value(item, visited_paths) for item in obj]

        return obj

    return resolve_value(resolved, [])


class ReferenceResolvingSettingsSource(PydanticBaseSettingsSource):
    """
    A settings source that wraps other sources and resolves ${path} references.
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        sources: tuple[PydanticBaseSettingsSource, ...],
    ):
        super().__init__(settings_cls)
        self.sources = sources

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        merged_data: dict[str, Any] = {}

        for source in reversed(self.sources):
            source_data = source()
            if source_data:
                merged_data = self._deep_merge(merged_data, source_data)

        return resolve_config_references(merged_data)

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        result = base.copy()
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = ReferenceResolvingSettingsSource._deep_merge(
                    result[key], value
                )
            else:
                result[key] = value
        return result


class YamlConfigSettingsSource(PydanticBaseSettingsSource):
    """
    A generic source that loads a YAML file into a dictionary.
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        file_path: Path | str | None,
    ):
        super().__init__(settings_cls)
        self.file_path = file_path

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        if not self.file_path or not os.path.exists(self.file_path):
            return {}

        try:
            with open(self.file_path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}  # type: ignore
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "Failed to load config file %s: %s", self.file_path, e
            )
            return {}


def find_project_root(
    anchor_file: str = "default.yaml", search_folder: str = "config"
) -> Path:
    """
    Traverses up the file system to find the directory containing the config folder.
    """
    current_path = Path(__file__).resolve().parent
    root = Path(current_path.root)

    while current_path != root:
        potential_path = current_path / search_folder
        if potential_path.is_dir() and (potential_path / anchor_file).exists():
            return potential_path
        current_path = current_path.parent

    return Path(os.getcwd()) / search_folder
