# src/app/core/config/domain.py
from typing import Any

from pydantic import BaseModel, Field

# --- Sub-Models ---


class Contact(BaseModel):
    name: str
    url: str
    email: str


class LicenseInfo(BaseModel):
    name: str
    url: str


class AppConfig(BaseModel):
    title: str
    description: str
    version: str
    terms_of_service: str
    contact: Contact
    license_info: LicenseInfo


class CorsConfig(BaseModel):
    enabled: bool
    allow_origins: list[str]
    allow_credentials: bool
    allow_methods: list[str]
    allow_headers: list[str]
    max_age: int


class ServerConfig(BaseModel):
    host: str
    port: int
    log_level: str = "debug"
    reload: bool = False
    max_workers: int | None = 1
    cors: CorsConfig


class HandlerConfig(BaseModel):
    class_: str = Field(..., alias="class")
    level: str | None = None
    formatter: str | None = None
    stream: str | None = None
    filename: str | None = None


class LoggerConfig(BaseModel):
    level: str | None = None
    handlers: list[str]
    propagate: bool | None = None


class LoggingConfig(BaseModel):
    version: int
    formatters: dict[str, dict[str, Any]]
    handlers: dict[str, HandlerConfig]
    loggers: dict[str, LoggerConfig]
    root: LoggerConfig


class AuditConfig(BaseModel):
    enabled: bool = Field(True, description="Master switch for audit logging")
    log_request_body: bool = Field(False)
    max_body_size: int = Field(51200)
    excluded_paths: set[str] = {
        "/health",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/favicon.ico",
    }
    excluded_methods: set[str] = {"OPTIONS", "HEAD"}
