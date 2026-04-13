use axum::extract::State;
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::routing::get;
use axum::{Json, Router};
use serde_json::json;
use sqlx::PgPool;

pub fn routes() -> Router<PgPool> {
    Router::new()
        .route("/live", get(liveness))
        .route("/ready", get(readiness))
}

async fn liveness() -> impl IntoResponse {
    Json(json!({
        "status": "UP",
        "details": "Service is running"
    }))
}

async fn readiness(State(pool): State<PgPool>) -> impl IntoResponse {
    let db_status = match sqlx::query("SELECT 1").execute(&pool).await {
        Ok(_) => json!({ "status": "UP" }),
        Err(e) => json!({ "status": "DOWN", "error": e.to_string() }),
    };

    let overall = if db_status["status"] == "UP" {
        "UP"
    } else {
        "DOWN"
    };

    let status_code = if overall == "UP" {
        StatusCode::OK
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    };

    (
        status_code,
        Json(json!({
            "status": overall,
            "components": {
                "database": db_status
            },
            "systemInfo": {
                "rustVersion": option_env!("CARGO_PKG_RUST_VERSION").unwrap_or("unknown"),
                "platform": std::env::consts::OS
            }
        })),
    )
}
