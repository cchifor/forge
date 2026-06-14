# src/app/core/config/domain.py
import os
from typing import Any

from pydantic import BaseModel, Field, model_validator

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

    @model_validator(mode="after")
    def _reject_wildcard_with_credentials_in_prod(self) -> "CorsConfig":
        # The gatekeeper IS the auth/BFF edge, so a reflected-origin +
        # credentials CORS posture is especially dangerous here. Mirror the
        # generated service guard: when CORS is enabled, refuse
        # allow_origins=['*'] + allow_credentials=True in a production posture
        # (Starlette reflects any origin for credentialed requests). Dev/test
        # keep the permissive default for local cross-origin work.
        if not self.enabled:
            return self
        env = os.getenv("ENV", os.getenv("ENVIRONMENT", "production")).strip().lower()
        if env in ("development", "dev", "local", "test", "testing", "ci"):
            return self
        if self.allow_credentials and "*" in self.allow_origins:
            raise ValueError(
                "CORS allow_origins=['*'] with allow_credentials=True reflects "
                "any origin for credentialed requests — refused in production. "
                "List the exact allowed origins, or set allow_credentials=False."
            )
        return self


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
