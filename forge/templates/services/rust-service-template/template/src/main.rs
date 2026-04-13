use dotenvy::dotenv;
use std::net::SocketAddr;
use tracing_subscriber::EnvFilter;

mod app;
mod client;
mod config;
mod db;
mod errors;
mod middleware;
mod models;
mod routes;
mod services;

#[tokio::main]
async fn main() {
    dotenv().ok();
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env().add_directive("info".parse().unwrap()))
        .json()
        .init();

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
