use axum::Router;
use sqlx::PgPool;
use tower_http::cors::CorsLayer;

use crate::middleware::correlation::{propagate_request_id_layer, set_request_id_layer};
use crate::routes;

pub fn create_app(pool: PgPool) -> Router {
    Router::new()
        .nest("/api/v1", routes::api_routes())
        .with_state(pool)
        .layer(propagate_request_id_layer())
        .layer(set_request_id_layer())
        .layer(CorsLayer::permissive())
}
