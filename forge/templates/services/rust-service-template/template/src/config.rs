//! RFC-008 layered config loader for the Rust backend.
//!
//! Priority (highest wins):
//!   1. Env vars prefixed `APP__` (nested keys via `__`, e.g.
//!      `APP__SERVER__PORT=8080`).
//!   2. `.secrets.yaml` (gitignored; for local dev secrets).
//!   3. `config/<ENV>.yaml` (selected by `ENV` env var, defaults to `development`).
//!   4. `config/defaults.yaml`.
//!   5. Struct defaults.

use config::{Config as ConfigBuilder, ConfigError, Environment, File, FileFormat};
use serde::Deserialize;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Deserialize)]
pub struct AppInfo {
    #[serde(default = "default_name")]
    pub name: String,
    #[serde(default = "default_version")]
    pub version: String,
    #[serde(default = "default_env")]
    pub env: String,
}

fn default_name() -> String {
    "service".to_string()
}

fn default_version() -> String {
    "0.0.0".to_string()
}

fn default_env() -> String {
    "development".to_string()
}

impl Default for AppInfo {
    fn default() -> Self {
        Self {
            name: default_name(),
            version: default_version(),
            env: default_env(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct CorsConfig {
    #[serde(default = "default_cors_enabled")]
    pub enabled: bool,
    #[serde(default = "default_cors_origins")]
    pub allow_origins: Vec<String>,
    #[serde(default)]
    pub allow_credentials: bool,
    #[serde(default = "default_cors_max_age")]
    pub max_age: u64,
}

fn default_cors_enabled() -> bool {
    true
}

fn default_cors_origins() -> Vec<String> {
    vec!["*".to_string()]
}

fn default_cors_max_age() -> u64 {
    600
}

impl Default for CorsConfig {
    fn default() -> Self {
        Self {
            enabled: default_cors_enabled(),
            allow_origins: default_cors_origins(),
            allow_credentials: false,
            max_age: default_cors_max_age(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct ServerConfig {
    #[serde(default = "default_host")]
    pub host: String,
    #[serde(default = "default_port")]
    pub port: u16,
    #[serde(default)]
    pub cors: CorsConfig,
}

fn default_host() -> String {
    "0.0.0.0".to_string()
}

fn default_port() -> u16 {
    5000
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            host: default_host(),
            port: default_port(),
            cors: CorsConfig::default(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct DbConfig {
    pub url: String,
    #[serde(default = "default_pool_min")]
    pub pool_min: u32,
    #[serde(default = "default_pool_max")]
    pub pool_max: u32,
    #[serde(default = "default_statement_timeout_ms")]
    pub statement_timeout_ms: u64,
}

fn default_pool_min() -> u32 {
    2
}

fn default_pool_max() -> u32 {
    10
}

fn default_statement_timeout_ms() -> u64 {
    30_000
}

#[derive(Debug, Clone, Deserialize)]
pub struct LoggingConfig {
    #[serde(default = "default_log_level")]
    pub level: String,
    #[serde(default)]
    pub pretty: bool,
}

fn default_log_level() -> String {
    "info".to_string()
}

impl Default for LoggingConfig {
    fn default() -> Self {
        Self {
            level: default_log_level(),
            pretty: false,
        }
    }
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct AuthConfig {
    #[serde(default)]
    pub enabled: bool,
    pub server_url: Option<String>,
    pub realm: Option<String>,
    pub client_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct SecurityConfig {
    #[serde(default)]
    pub auth: AuthConfig,
}

#[derive(Debug, Clone, Deserialize)]
pub struct AppConfig {
    #[serde(default)]
    pub app: AppInfo,
    #[serde(default)]
    pub server: ServerConfig,
    pub db: DbConfig,
    #[serde(default)]
    pub logging: LoggingConfig,
    #[serde(default)]
    pub security: SecurityConfig,
}

/// Backwards-compatible shim — older code paths read `Config::from_env()`
/// and only care about `port` + `database_url`.
pub struct Config {
    pub port: u16,
    pub database_url: String,
}

impl From<&AppConfig> for Config {
    fn from(cfg: &AppConfig) -> Self {
        Self {
            port: cfg.server.port,
            database_url: cfg.db.url.clone(),
        }
    }
}

impl Config {
    /// Convenience for call sites that only need port + database url.
    pub fn from_env() -> Self {
        let cfg = AppConfig::load().expect("failed to load config");
        Config::from(&cfg)
    }
}

pub struct LoadOptions {
    pub project_root: Option<PathBuf>,
    pub env: Option<String>,
}

impl Default for LoadOptions {
    fn default() -> Self {
        Self {
            project_root: None,
            env: None,
        }
    }
}

impl AppConfig {
    /// Load layered config from the conventional layout. See module docs.
    pub fn load() -> Result<Self, ConfigError> {
        Self::load_with(LoadOptions::default())
    }

    pub fn load_with(options: LoadOptions) -> Result<Self, ConfigError> {
        let project_root = options
            .project_root
            .clone()
            .unwrap_or_else(|| std::env::current_dir().expect("cwd"));
        let env = options
            .env
            .clone()
            .or_else(|| std::env::var("ENV").ok())
            .or_else(|| std::env::var("APP_ENV").ok())
            .unwrap_or_else(|| "development".to_string());

        let config_dir = project_root.join("config");
        let defaults_path = config_dir.join("defaults.yaml");
        let env_path = config_dir.join(format!("{env}.yaml"));
        let secrets_path = project_root.join(".secrets.yaml");

        let mut builder = ConfigBuilder::builder()
            .add_source(
                File::from(defaults_path.as_path())
                    .required(false)
                    .format(FileFormat::Yaml),
            )
            .add_source(
                File::from(env_path.as_path())
                    .required(false)
                    .format(FileFormat::Yaml),
            );

        if Path::new(&secrets_path).exists() {
            builder = builder.add_source(
                File::from(secrets_path.as_path())
                    .required(false)
                    .format(FileFormat::Yaml),
            );
        }

        builder = builder.add_source(
            Environment::with_prefix("APP")
                .separator("__")
                .try_parsing(true)
                .list_separator(",")
                .with_list_parse_key("server.cors.allow_origins"),
        );

        builder = builder.set_override("app.env", env.clone())?;

        let built = builder.build()?;
        built.try_deserialize::<AppConfig>()
    }
}
