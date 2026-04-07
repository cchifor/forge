mod health;
mod home;
mod items;

use axum::Router;
use sqlx::PgPool;

pub fn api_routes() -> Router<PgPool> {
    Router::new()
        .merge(home::routes())
        .nest("/health", health::routes())
        .nest("/items", items::routes())
}
