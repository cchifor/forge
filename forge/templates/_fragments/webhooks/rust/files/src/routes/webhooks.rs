//! /api/v1/webhooks CRUD + /test-fire endpoints.

use axum::extract::Path;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Json};
use axum::routing::{delete, get, post};
use axum::Router;
use serde_json::{json, Value};
use uuid::Uuid;

use crate::services::webhooks::{
    create_webhook, delete_webhook, deliver, get_webhook, list_webhooks, WebhookCreate,
};

pub fn routes<S>() -> Router<S>
where
    S: Clone + Send + Sync + 'static,
{
    Router::new()
        .route("/", get(list_handler).post(create_handler))
        .route("/{id}", delete(delete_handler))
        .route("/{id}/test", post(test_handler))
}

async fn list_handler() -> impl IntoResponse {
    Json(json!({ "webhooks": list_webhooks() }))
}

async fn create_handler(Json(body): Json<WebhookCreate>) -> impl IntoResponse {
    let webhook = create_webhook(body);
    (StatusCode::CREATED, Json(webhook))
}

async fn delete_handler(Path(id): Path<Uuid>) -> impl IntoResponse {
    if delete_webhook(&id) {
        StatusCode::NO_CONTENT
    } else {
        StatusCode::NOT_FOUND
    }
}

async fn test_handler(Path(id): Path<Uuid>) -> impl IntoResponse {
    let Some(webhook) = get_webhook(&id) else {
        return (
            StatusCode::NOT_FOUND,
            Json(json!({ "detail": "webhook not found" })),
        )
            .into_response();
    };
    let payload: Value = json!({ "message": "forge webhook test" });
    let result = deliver(&webhook, "webhook.test", &payload).await;
    Json(result).into_response()
}
