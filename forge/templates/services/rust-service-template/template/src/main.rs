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

use dotenvy::dotenv;
use std::net::SocketAddr;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{fmt, EnvFilter};

mod app;
mod client;
mod config;
mod data;
mod db;
mod errors;
mod middleware;
mod models;
mod routes;
mod services;
// FORGE:MAIN_MOD_REGISTRATION

#[tokio::main]
async fn main() {
    dotenv().ok();

    let env_filter =
        EnvFilter::from_default_env().add_directive("info".parse().unwrap());
    let registry = tracing_subscriber::registry()
        .with(env_filter)
        .with(fmt::layer().json());
    // FORGE:TRACING_LAYERS
    registry.init();

    let pool = db::create_pool().await;
    let app = app::create_app(pool);
    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(5000);
    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    tracing::info!("Server running on {}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
