from typing import Any, Literal

from pydantic import BaseModel, Field

from service.domain.config import AuthConfig


class Contact(BaseModel):
    name: str = ""
    url: str | None = None
    email: str = ""


class LicenseInfo(BaseModel):
    name: str = "MIT"
    url: str | None = None


class AppConfig(BaseModel):
    title: str = "My Service"
    description: str = "A Python microservice"
    version: str = "0.1.0"
    terms_of_service: str | None = None
    contact: Contact = Contact()
    license_info: LicenseInfo = LicenseInfo()


class CorsConfig(BaseModel):
    enabled: bool = False
    allow_origins: list[str] = ["*"]
    allow_credentials: bool = True
    allow_methods: list[str] = ["*"]
    allow_headers: list[str] = ["*"]
    max_age: int = 3600


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 5000
    log_level: str = "critical"
    reload: bool = False
    max_workers: int | None = 1
    cors: CorsConfig = CorsConfig()


class DiscoveryConfig(BaseModel):
    enabled: bool = False
    app_name: str = "my-service"
    service_url: str = "http://localhost:8761/eureka"
    service_port: int = 5000
    service_user: str = ""
    service_password: str = ""
    instance_ip: str = ""
    instance_host: str = ""
    instance_port: int = 5000


class SecurityConfig(BaseModel):
    algorithm: str = "HS256"
    secret_key: str = Field("CHANGEME", description="Must be overridden in production")
    access_token_expire_minutes: int = 30
    refresh_token_expire_minutes: int = 60
    auth: AuthConfig


class DbConfig(BaseModel):
    url: str = Field(
        "sqlite+aiosqlite:///development.db",
        description="Full database connection URL",
    )
    pool_size: int = Field(10, ge=1)
    max_overflow: int = Field(20, ge=0)
    pool_timeout: int = Field(30, ge=1)
    pool_recycle: int = Field(3600, ge=-1)
    echo: bool | Literal["debug"] = Field(False)
    application_name: str = Field("my-service")
    ssl_mode: Literal["disable", "prefer", "require"] | None = None


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
    version: int = 1
    formatters: dict[str, dict[str, Any]] = {}
    handlers: dict[str, HandlerConfig] = {}
    loggers: dict[str, LoggerConfig] = {}
    root: LoggerConfig = LoggerConfig(handlers=["console"])


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
