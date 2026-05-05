use axum::Router;
use sqlx::PgPool;
use tower_http::cors::CorsLayer;

use crate::middleware::correlation::{propagate_request_id_layer, set_request_id_layer};
use crate::routes;
// FORGE:BEGIN rate_limit:MIDDLEWARE_IMPORTS
use crate::middleware::rate_limit::rate_limit_middleware;
// FORGE:END rate_limit:MIDDLEWARE_IMPORTS
// FORGE:BEGIN security_headers:MIDDLEWARE_IMPORTS
use crate::middleware::security_headers::security_headers_middleware;
// FORGE:END security_headers:MIDDLEWARE_IMPORTS
// FORGE:MIDDLEWARE_IMPORTS

// ``#[rustfmt::skip]`` — fragment injection sites pin the indent of the
// FORGE marker comments; rustfmt would shift them out of the chain when no
// ``.layer(...)`` follows the last marker, breaking subsequent
// ``--update`` runs that re-inject against the marker. Skip the function
// rather than re-injecting on every cargo fmt.
#[rustfmt::skip]
pub fn create_app(pool: PgPool) -> Router {
    Router::new()
        .nest("/api/v1", routes::api_routes())
        .with_state(pool)
        .layer(propagate_request_id_layer())
        .layer(set_request_id_layer())
        .layer(CorsLayer::permissive())
        // FORGE:BEGIN rate_limit:MIDDLEWARE_REGISTRATION
        .layer(axum::middleware::from_fn(rate_limit_middleware))
        // FORGE:END rate_limit:MIDDLEWARE_REGISTRATION
        // FORGE:BEGIN security_headers:MIDDLEWARE_REGISTRATION
        .layer(axum::middleware::from_fn(security_headers_middleware))
        // FORGE:END security_headers:MIDDLEWARE_REGISTRATION
        // FORGE:MIDDLEWARE_REGISTRATION
}
