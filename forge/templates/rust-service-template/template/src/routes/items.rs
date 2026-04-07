use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::routing::get;
use axum::{Json, Router};
use sqlx::PgPool;
use uuid::Uuid;

use crate::errors::AppError;
use crate::models::{CreateItem, ListParams, UpdateItem};
use crate::services::item_service;

pub fn routes() -> Router<PgPool> {
    Router::new()
        .route("/", get(list_items).post(create_item))
        .route(
            "/{id}",
            get(get_item).patch(update_item).delete(delete_item),
        )
}

async fn list_items(
    State(pool): State<PgPool>,
    Query(params): Query<ListParams>,
) -> Result<impl IntoResponse, AppError> {
    let result = item_service::list(&pool, params).await?;
    Ok(Json(result))
}

async fn create_item(
    State(pool): State<PgPool>,
    Json(body): Json<CreateItem>,
) -> Result<impl IntoResponse, AppError> {
    let item = item_service::create(&pool, body).await?;
    Ok((StatusCode::CREATED, Json(item)))
}

async fn get_item(
    State(pool): State<PgPool>,
    Path(id): Path<Uuid>,
) -> Result<impl IntoResponse, AppError> {
    let item = item_service::get_by_id(&pool, id).await?;
    Ok(Json(item))
}

async fn update_item(
    State(pool): State<PgPool>,
    Path(id): Path<Uuid>,
    Json(body): Json<UpdateItem>,
) -> Result<impl IntoResponse, AppError> {
    let item = item_service::update(&pool, id, body).await?;
    Ok(Json(item))
}

async fn delete_item(
    State(pool): State<PgPool>,
    Path(id): Path<Uuid>,
) -> Result<impl IntoResponse, AppError> {
    item_service::delete(&pool, id).await?;
    Ok(StatusCode::NO_CONTENT)
}
