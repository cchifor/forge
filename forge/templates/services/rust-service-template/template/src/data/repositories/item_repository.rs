//! Tenant-aware repository for the `items` table.

use async_trait::async_trait;
use sqlx::PgPool;
use uuid::Uuid;

use crate::errors::AppError;
use crate::middleware::tenant::TenantContext;
use crate::models::{CreateItem, Item, ListParams, PaginatedResponse, UpdateItem};

/// Persistence contract for the `items` table.
///
/// Every method is tenant-scoped — the implementation must add a
/// `customer_id = tenant.customer_id` clause to every query.
#[async_trait]
pub trait ItemRepository: Send + Sync {
    async fn list(
        &self,
        tenant: &TenantContext,
        params: ListParams,
    ) -> Result<PaginatedResponse<Item>, AppError>;

    async fn get_by_id(&self, tenant: &TenantContext, id: Uuid) -> Result<Option<Item>, AppError>;

    async fn find_by_name(
        &self,
        tenant: &TenantContext,
        name: &str,
    ) -> Result<Option<Item>, AppError>;

    async fn find_by_name_excluding(
        &self,
        tenant: &TenantContext,
        name: &str,
        exclude_id: Uuid,
    ) -> Result<Option<Item>, AppError>;

    async fn create(&self, tenant: &TenantContext, data: CreateItem) -> Result<Item, AppError>;

    async fn update(
        &self,
        tenant: &TenantContext,
        id: Uuid,
        data: UpdateItem,
    ) -> Result<Item, AppError>;

    async fn delete(&self, tenant: &TenantContext, id: Uuid) -> Result<(), AppError>;
}

/// Postgres-backed implementation built on sqlx.
pub struct PgItemRepository {
    pool: PgPool,
}

impl PgItemRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

#[async_trait]
impl ItemRepository for PgItemRepository {
    async fn list(
        &self,
        tenant: &TenantContext,
        params: ListParams,
    ) -> Result<PaginatedResponse<Item>, AppError> {
        let skip = params.skip.unwrap_or(0);
        let limit = params.limit.unwrap_or(20).min(100);

        let mut conditions = vec!["customer_id = $1".to_string()];
        let mut bind_idx = 1u32;

        if params.status.is_some() {
            bind_idx += 1;
            conditions.push(format!("status = ${bind_idx}"));
        }
        if params.search.is_some() {
            bind_idx += 1;
            let name_idx = bind_idx;
            bind_idx += 1;
            let desc_idx = bind_idx;
            conditions.push(format!(
                "(name ILIKE ${name_idx} OR description ILIKE ${desc_idx})"
            ));
        }

        let where_clause = format!("WHERE {}", conditions.join(" AND "));
        let count_sql = format!("SELECT COUNT(*) as count FROM items {where_clause}");
        let query_sql = format!(
            "SELECT * FROM items {where_clause} ORDER BY created_at DESC LIMIT ${} OFFSET ${}",
            bind_idx + 1,
            bind_idx + 2,
        );

        let mut count_query = sqlx::query_scalar::<_, i64>(&count_sql);
        count_query = count_query.bind(tenant.customer_id);
        if let Some(ref status) = params.status {
            count_query = count_query.bind(status);
        }
        if let Some(ref search) = params.search {
            let pattern = format!("%{search}%");
            count_query = count_query.bind(pattern.clone()).bind(pattern);
        }
        let total = count_query.fetch_one(&self.pool).await?;

        let mut items_query = sqlx::query_as::<_, Item>(&query_sql);
        items_query = items_query.bind(tenant.customer_id);
        if let Some(ref status) = params.status {
            items_query = items_query.bind(status);
        }
        if let Some(ref search) = params.search {
            let pattern = format!("%{search}%");
            items_query = items_query.bind(pattern.clone()).bind(pattern);
        }
        items_query = items_query.bind(limit).bind(skip);
        let items = items_query.fetch_all(&self.pool).await?;

        Ok(PaginatedResponse {
            items,
            total,
            skip,
            limit,
            has_more: skip + limit < total,
        })
    }

    async fn get_by_id(&self, tenant: &TenantContext, id: Uuid) -> Result<Option<Item>, AppError> {
        let item =
            sqlx::query_as::<_, Item>("SELECT * FROM items WHERE id = $1 AND customer_id = $2")
                .bind(id)
                .bind(tenant.customer_id)
                .fetch_optional(&self.pool)
                .await?;
        Ok(item)
    }

    async fn find_by_name(
        &self,
        tenant: &TenantContext,
        name: &str,
    ) -> Result<Option<Item>, AppError> {
        let item =
            sqlx::query_as::<_, Item>("SELECT * FROM items WHERE name = $1 AND customer_id = $2")
                .bind(name)
                .bind(tenant.customer_id)
                .fetch_optional(&self.pool)
                .await?;
        Ok(item)
    }

    async fn find_by_name_excluding(
        &self,
        tenant: &TenantContext,
        name: &str,
        exclude_id: Uuid,
    ) -> Result<Option<Item>, AppError> {
        let item = sqlx::query_as::<_, Item>(
            "SELECT * FROM items WHERE name = $1 AND customer_id = $2 AND id != $3",
        )
        .bind(name)
        .bind(tenant.customer_id)
        .bind(exclude_id)
        .fetch_optional(&self.pool)
        .await?;
        Ok(item)
    }

    async fn create(&self, tenant: &TenantContext, data: CreateItem) -> Result<Item, AppError> {
        let tags = data.tags.unwrap_or(serde_json::json!([]));
        let status = data.status.unwrap_or_else(|| "DRAFT".to_string());

        let item = sqlx::query_as::<_, Item>(
            r#"
            INSERT INTO items (name, description, tags, status, customer_id, user_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
            "#,
        )
        .bind(&data.name)
        .bind(&data.description)
        .bind(&tags)
        .bind(&status)
        .bind(tenant.customer_id)
        .bind(tenant.user_id)
        .fetch_one(&self.pool)
        .await?;
        Ok(item)
    }

    async fn update(
        &self,
        tenant: &TenantContext,
        id: Uuid,
        data: UpdateItem,
    ) -> Result<Item, AppError> {
        let mut sets = Vec::new();
        let mut bind_idx = 0u32;

        if data.name.is_some() {
            bind_idx += 1;
            sets.push(format!("name = ${bind_idx}"));
        }
        if data.description.is_some() {
            bind_idx += 1;
            sets.push(format!("description = ${bind_idx}"));
        }
        if data.tags.is_some() {
            bind_idx += 1;
            sets.push(format!("tags = ${bind_idx}"));
        }
        if data.status.is_some() {
            bind_idx += 1;
            sets.push(format!("status = ${bind_idx}"));
        }

        if sets.is_empty() {
            // Nothing to patch — return the row unchanged.
            return self
                .get_by_id(tenant, id)
                .await?
                .ok_or_else(|| AppError::not_found("Item", id.to_string()));
        }

        sets.push("updated_at = NOW()".to_string());
        bind_idx += 1;
        let id_idx = bind_idx;
        bind_idx += 1;
        let cust_idx = bind_idx;

        let sql = format!(
            "UPDATE items SET {} WHERE id = ${id_idx} AND customer_id = ${cust_idx} RETURNING *",
            sets.join(", ")
        );

        let mut query = sqlx::query_as::<_, Item>(&sql);
        if let Some(ref name) = data.name {
            query = query.bind(name);
        }
        if let Some(ref description) = data.description {
            query = query.bind(description);
        }
        if let Some(ref tags) = data.tags {
            query = query.bind(tags);
        }
        if let Some(ref status) = data.status {
            query = query.bind(status);
        }
        query = query.bind(id).bind(tenant.customer_id);

        let item = query.fetch_one(&self.pool).await?;
        Ok(item)
    }

    async fn delete(&self, tenant: &TenantContext, id: Uuid) -> Result<(), AppError> {
        sqlx::query("DELETE FROM items WHERE id = $1 AND customer_id = $2")
            .bind(id)
            .bind(tenant.customer_id)
            .execute(&self.pool)
            .await?;
        Ok(())
    }
}
