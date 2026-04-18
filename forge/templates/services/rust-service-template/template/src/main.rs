use dotenvy::dotenv;
use std::net::SocketAddr;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{fmt, EnvFilter};

mod app;
mod client;
mod config;
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
