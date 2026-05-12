//! Service layer.
//!
//! Depends on the [`ItemRepository`] trait — any implementation,
//! including in-memory test doubles, satisfies the bound. The default
//! wiring uses [`PgItemRepository`].

use crate::identity::IdentityContext;
use sqlx::PgPool;
use uuid::Uuid;

use crate::data::repositories::{ItemRepository, PgItemRepository};
use crate::errors::AppError;
use crate::models::{CreateItem, Item, ListParams, PaginatedResponse, UpdateItem};

pub async fn list(
    pool: &PgPool,
    identity: &IdentityContext,
    params: ListParams,
) -> Result<PaginatedResponse<Item>, AppError> {
    let repo = PgItemRepository::new(pool.clone());
    repo.list(identity, params).await
}

pub async fn create(
    pool: &PgPool,
    identity: &IdentityContext,
    data: CreateItem,
) -> Result<Item, AppError> {
    let repo = PgItemRepository::new(pool.clone());
    if repo.find_by_name(identity, &data.name).await?.is_some() {
        return Err(AppError::already_exists("Item", &data.name));
    }
    repo.create(identity, data).await
}

pub async fn get_by_id(
    pool: &PgPool,
    identity: &IdentityContext,
    id: Uuid,
) -> Result<Item, AppError> {
    let repo = PgItemRepository::new(pool.clone());
    repo.get_by_id(identity, id)
        .await?
        .ok_or_else(|| AppError::not_found("Item", id.to_string()))
}

pub async fn update(
    pool: &PgPool,
    identity: &IdentityContext,
    id: Uuid,
    data: UpdateItem,
) -> Result<Item, AppError> {
    let repo = PgItemRepository::new(pool.clone());
    repo.get_by_id(identity, id)
        .await?
        .ok_or_else(|| AppError::not_found("Item", id.to_string()))?;

    if let Some(ref name) = data.name {
        if repo
            .find_by_name_excluding(identity, name, id)
            .await?
            .is_some()
        {
            return Err(AppError::already_exists("Item", name));
        }
    }

    repo.update(identity, id, data).await
}

pub async fn delete(pool: &PgPool, identity: &IdentityContext, id: Uuid) -> Result<(), AppError> {
    let repo = PgItemRepository::new(pool.clone());
    repo.get_by_id(identity, id)
        .await?
        .ok_or_else(|| AppError::not_found("Item", id.to_string()))?;
    repo.delete(identity, id).await
}
