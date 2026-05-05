//! Service layer.
//!
//! Depends on the [`ItemRepository`] trait — any implementation,
//! including in-memory test doubles, satisfies the bound. The default
//! wiring uses [`PgItemRepository`].

use sqlx::PgPool;
use uuid::Uuid;

use crate::data::repositories::{ItemRepository, PgItemRepository};
use crate::errors::AppError;
use crate::middleware::tenant::TenantContext;
use crate::models::{CreateItem, Item, ListParams, PaginatedResponse, UpdateItem};

pub async fn list(
    pool: &PgPool,
    tenant: &TenantContext,
    params: ListParams,
) -> Result<PaginatedResponse<Item>, AppError> {
    let repo = PgItemRepository::new(pool.clone());
    repo.list(tenant, params).await
}

pub async fn create(
    pool: &PgPool,
    tenant: &TenantContext,
    data: CreateItem,
) -> Result<Item, AppError> {
    let repo = PgItemRepository::new(pool.clone());
    if repo.find_by_name(tenant, &data.name).await?.is_some() {
        return Err(AppError::already_exists("Item", &data.name));
    }
    repo.create(tenant, data).await
}

pub async fn get_by_id(pool: &PgPool, tenant: &TenantContext, id: Uuid) -> Result<Item, AppError> {
    let repo = PgItemRepository::new(pool.clone());
    repo.get_by_id(tenant, id)
        .await?
        .ok_or_else(|| AppError::not_found("Item", id.to_string()))
}

pub async fn update(
    pool: &PgPool,
    tenant: &TenantContext,
    id: Uuid,
    data: UpdateItem,
) -> Result<Item, AppError> {
    let repo = PgItemRepository::new(pool.clone());
    repo.get_by_id(tenant, id)
        .await?
        .ok_or_else(|| AppError::not_found("Item", id.to_string()))?;

    if let Some(ref name) = data.name {
        if repo
            .find_by_name_excluding(tenant, name, id)
            .await?
            .is_some()
        {
            return Err(AppError::already_exists("Item", name));
        }
    }

    repo.update(tenant, id, data).await
}

pub async fn delete(pool: &PgPool, tenant: &TenantContext, id: Uuid) -> Result<(), AppError> {
    let repo = PgItemRepository::new(pool.clone());
    repo.get_by_id(tenant, id)
        .await?
        .ok_or_else(|| AppError::not_found("Item", id.to_string()))?;
    repo.delete(tenant, id).await
}
