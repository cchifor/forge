// Generated scaffolding ships with infrastructure (config loaders, error
// variants, service-client helpers) ready for user code that may not exist
// yet. The CI lane runs ``cargo clippy --all-targets -- -D warnings`` which
// promotes every default-enabled clippy lint to a hard error; the
// scaffolding inevitably trips a handful (dead_code, pedantic style nits)
// on day one. Silence them crate-wide so the lane can pass on a fresh
// generation, then drop or narrow these allows as your service fills in.
#![allow(dead_code)]
#![allow(clippy::needless_pass_by_value)]
#![allow(clippy::too_many_arguments)]
#![allow(clippy::module_name_repetitions)]
#![allow(clippy::missing_errors_doc)]
#![allow(clippy::missing_panics_doc)]
#![allow(clippy::must_use_candidate)]
#![allow(clippy::collapsible_if)]
#![allow(clippy::derivable_impls)]

use dotenvy::dotenv;
use std::net::SocketAddr;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{EnvFilter, fmt};

mod app;
mod config;
mod data;
mod db;
mod errors;
mod identity;
mod middleware;
mod models;
mod routes;
mod services;
// FORGE:MAIN_MOD_REGISTRATION

#[tokio::main]
async fn main() {
    dotenv().ok();

    let env_filter = EnvFilter::from_default_env().add_directive("info".parse().unwrap());
    let registry = tracing_subscriber::registry()
        .with(env_filter)
        .with(fmt::layer().json());
    // FORGE:TRACING_LAYERS
    registry.init();

    // Load + validate config at startup so the fail-closed auth guard
    // (config::AppConfig::validate) actually runs: it rejects a production-like
    // env with auth enabled but GATEKEEPER_ISSUER/SERVICE_AUDIENCE unset.
    // Fail closed — exit non-zero rather than boot a misconfigured service.
    let config = match config::AppConfig::load() {
        Ok(cfg) => cfg,
        Err(e) => {
            tracing::error!("configuration error: {e}");
            std::process::exit(1);
        }
    };
    tracing::info!(env = %config.app.env, "configuration validated");

    // FORGE:STARTUP_INIT

    let pool = db::create_pool().await;
    let app = app::create_app(pool);
    // PORT env stays authoritative for the listen port (container/compose set
    // it); the validated config supplies the fallback.
    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(config.server.port);
    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    tracing::info!("Server running on {}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    // Graceful shutdown: a rollout sends SIGTERM; with_graceful_shutdown stops
    // accepting new connections and lets in-flight requests finish before the
    // process exits, instead of dropping them mid-response.
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
        .unwrap();
}

/// Resolve when the process receives SIGTERM (rollout) or Ctrl-C (SIGINT).
async fn shutdown_signal() {
    let ctrl_c = async {
        tokio::signal::ctrl_c()
            .await
            .expect("failed to install Ctrl-C handler");
    };

    #[cfg(unix)]
    let terminate = async {
        tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("failed to install SIGTERM handler")
            .recv()
            .await;
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }
    tracing::info!("shutdown signal received — draining connections");
}
