import datetime
import multiprocessing
import os
import sys
from typing import Any

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from . import domain, sources


class Settings(BaseSettings):
    """Master configuration class."""

    def __init__(self, **values: Any):
        if values:
            values = sources.resolve_config_references(values)
        super().__init__(**values)

    version: int = 1
    app: domain.AppConfig = domain.AppConfig()
    server: domain.ServerConfig = domain.ServerConfig()
    security: domain.SecurityConfig
    discovery: domain.DiscoveryConfig = domain.DiscoveryConfig()
    db: domain.DbConfig = domain.DbConfig()
    logging: domain.LoggingConfig = domain.LoggingConfig()
    audit: domain.AuditConfig = domain.AuditConfig()

    model_config = SettingsConfigDict(
        env_prefix="APP__",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    @staticmethod
    def _bootstrap_log(message: str, level: str = "INFO", stack_offset: int = 1) -> None:
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        pid = os.getpid()
        process_name = multiprocessing.current_process().name
        try:
            frame = sys._getframe(stack_offset + 1)
            line_no = frame.f_lineno
            filename = os.path.basename(frame.f_code.co_filename)
        except (AttributeError, ValueError):
            line_no = 0
            filename = "unknown"
        log_fmt = (
            f"{timestamp} - {pid} - {process_name} - {level} - "
            f"config - {filename}:{line_no} - {message}"
        )
        print(log_fmt, file=sys.stderr)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        env = os.getenv("ENV", "development")
        config_dir = sources.find_project_root()
        project_root = config_dir.parent

        default_yaml = config_dir / "default.yaml"
        env_yaml = config_dir / f"{env}.yaml"
        secrets_yaml = project_root / ".secrets.yaml"

        cls._bootstrap_log(f"Loading Configuration (ENV={env})")

        def _log_source_status(name: str, path: str, exists: bool, priority: int) -> None:
            status = "Found" if exists else "Missing (Skipping)"
            msg = f"Priority {priority}: {name:<15} -> {path} [{status}]"
            cls._bootstrap_log(msg, stack_offset=2)

        _log_source_status("Env Vars", f"Prefix: {cls.model_config.get('env_prefix')}", True, 1)
        _log_source_status("Secrets", str(secrets_yaml), secrets_yaml.exists(), 2)
        _log_source_status("Environment", str(env_yaml), env_yaml.exists(), 3)
        _log_source_status("Defaults", str(default_yaml), default_yaml.exists(), 4)

        standard_sources = (
            env_settings,
            sources.YamlConfigSettingsSource(settings_cls, secrets_yaml),
            sources.YamlConfigSettingsSource(settings_cls, env_yaml),
            sources.YamlConfigSettingsSource(settings_cls, default_yaml),
        )

        return (
            init_settings,
            sources.ReferenceResolvingSettingsSource(settings_cls, standard_sources),
        )
