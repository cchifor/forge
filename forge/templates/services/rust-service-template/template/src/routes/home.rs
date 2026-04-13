use axum::routing::get;
use axum::{Json, Router};
use serde_json::json;
use sqlx::PgPool;

pub fn routes() -> Router<PgPool> {
    Router::new()
        .route("/", get(welcome))
        .route("/info", get(info))
}

async fn welcome() -> Json<serde_json::Value> {
    Json(json!({ "message": "Welcome to the API" }))
}

async fn info() -> Json<serde_json::Value> {
    Json(json!({
        "title": env!("CARGO_PKG_NAME"),
        "version": env!("CARGO_PKG_VERSION"),
        "description": env!("CARGO_PKG_DESCRIPTION"),
    }))
}
