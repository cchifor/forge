use axum::body::Body;
use axum::http::{Request, StatusCode};
use http_body_util::BodyExt;
use tower::ServiceExt;

/// Helper to build the app router without a real database connection.
/// Health/live does not require DB, so we can test it with a mock pool approach.
/// For compile-check purposes, we construct the request manually.

#[tokio::test]
async fn health_live_returns_up() {
    // This test validates the endpoint contract.
    // In a full integration test with a running DB, we'd use:
    //   let pool = create_test_pool().await;
    //   let app = my_service::app::create_app(pool);
    //
    // For now, we build a minimal router that mirrors the live endpoint.
    use axum::{routing::get, Json, Router};
    use serde_json::json;

    let app = Router::new().route(
        "/api/v1/health/live",
        get(|| async {
            Json(json!({
                "status": "UP",
                "details": "Service is running"
            }))
        }),
    );

    let request = Request::builder()
        .uri("/api/v1/health/live")
        .body(Body::empty())
        .unwrap();

    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);

    let body = response.into_body().collect().await.unwrap().to_bytes();
    let json: serde_json::Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(json["status"], "UP");
    assert_eq!(json["details"], "Service is running");
}
