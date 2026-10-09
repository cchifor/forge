//! Tenant-aware repository for the `items` table.

use async_trait::async_trait;
use sqlx::{PgPool, Postgres, QueryBuilder};
use uuid::Uuid;

use crate::identity::IdentityContext;

use crate::errors::AppError;
use crate::models::{CreateItem, Item, ListParams, PaginatedResponse, UpdateItem};

/// Persistence contract for the `items` table.
///
/// Every method is tenant-scoped — the implementation must add a
/// `customer_id = identity.tenant_id` clause to every query.
#[async_trait]
pub trait ItemRepository: Send + Sync {
    async fn list(
        &self,
        identity: &IdentityContext,
        params: ListParams,
    ) -> Result<PaginatedResponse<Item>, AppError>;

    async fn get_by_id(
        &self,
        identity: &IdentityContext,
        id: Uuid,
    ) -> Result<Option<Item>, AppError>;

    async fn find_by_name(
        &self,
        identity: &IdentityContext,
        name: &str,
    ) -> Result<Option<Item>, AppError>;

    async fn find_by_name_excluding(
        &self,
        identity: &IdentityContext,
        name: &str,
        exclude_id: Uuid,
    ) -> Result<Option<Item>, AppError>;

    async fn create(&self, identity: &IdentityContext, data: CreateItem) -> Result<Item, AppError>;

    async fn update(
        &self,
        identity: &IdentityContext,
        id: Uuid,
        data: UpdateItem,
    ) -> Result<Item, AppError>;

    async fn delete(&self, identity: &IdentityContext, id: Uuid) -> Result<(), AppError>;
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
        identity: &IdentityContext,
        params: ListParams,
    ) -> Result<PaginatedResponse<Item>, AppError> {
        let skip = params.skip.unwrap_or(0);
        let limit = params.limit.unwrap_or(20);
        // Reject out-of-range pagination with a 422 instead of binding a
        // negative LIMIT/OFFSET into SQL (Postgres errors -> HTTP 500). Matches
        // Python's Query(ge=1) 422 and Node's z.min(1) 400. (audit #13)
        if skip < 0 || limit < 1 {
            return Err(AppError::Validation(
                "pagination out of range: 'limit' must be >= 1 and 'skip' must be >= 0".to_string(),
            ));
        }
        let limit = limit.min(100);

        let mut count_query = filtered_items_query("SELECT COUNT(*) FROM items", identity, &params);
        let total = count_query
            .build_query_scalar::<i64>()
            .fetch_one(&self.pool)
            .await?;

        let mut items_query = filtered_items_query("SELECT * FROM items", identity, &params);
        items_query
            .push(" ORDER BY created_at DESC LIMIT ")
            .push_bind(limit)
            .push(" OFFSET ")
            .push_bind(skip);
        let items = items_query
            .build_query_as::<Item>()
            .fetch_all(&self.pool)
            .await?;

        Ok(PaginatedResponse {
            items,
            total,
            skip,
            limit,
            has_more: skip + limit < total,
        })
    }

    async fn get_by_id(
        &self,
        identity: &IdentityContext,
        id: Uuid,
    ) -> Result<Option<Item>, AppError> {
        let item =
            sqlx::query_as::<_, Item>("SELECT * FROM items WHERE id = $1 AND customer_id = $2")
                .bind(id)
                .bind(identity.tenant_id)
                .fetch_optional(&self.pool)
                .await?;
        Ok(item)
    }

    async fn find_by_name(
        &self,
        identity: &IdentityContext,
        name: &str,
    ) -> Result<Option<Item>, AppError> {
        let item =
            sqlx::query_as::<_, Item>("SELECT * FROM items WHERE name = $1 AND customer_id = $2")
                .bind(name)
                .bind(identity.tenant_id)
                .fetch_optional(&self.pool)
                .await?;
        Ok(item)
    }

    async fn find_by_name_excluding(
        &self,
        identity: &IdentityContext,
        name: &str,
        exclude_id: Uuid,
    ) -> Result<Option<Item>, AppError> {
        let item = sqlx::query_as::<_, Item>(
            "SELECT * FROM items WHERE name = $1 AND customer_id = $2 AND id != $3",
        )
        .bind(name)
        .bind(identity.tenant_id)
        .bind(exclude_id)
        .fetch_optional(&self.pool)
        .await?;
        Ok(item)
    }

    async fn create(&self, identity: &IdentityContext, data: CreateItem) -> Result<Item, AppError> {
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
        .bind(identity.tenant_id)
        .bind(Uuid::parse_str(&identity.subject).unwrap_or_default())
        .fetch_one(&self.pool)
        .await?;
        Ok(item)
    }

    async fn update(
        &self,
        identity: &IdentityContext,
        id: Uuid,
        data: UpdateItem,
    ) -> Result<Item, AppError> {
        if data.name.is_none()
            && data.description.is_none()
            && data.tags.is_none()
            && data.status.is_none()
        {
            // Nothing to patch — return the row unchanged.
            return self
                .get_by_id(identity, id)
                .await?
                .ok_or_else(|| AppError::not_found("Item", id.to_string()));
        }
        let mut query = QueryBuilder::<Postgres>::new("UPDATE items SET ");
        if let Some(ref name) = data.name {
            query.push("name = ").push_bind(name).push(", ");
        }
        if let Some(ref description) = data.description {
            query
                .push("description = ")
                .push_bind(description)
                .push(", ");
        }
        if let Some(ref tags) = data.tags {
            query.push("tags = ").push_bind(tags).push(", ");
        }
        if let Some(ref status) = data.status {
            query.push("status = ").push_bind(status).push(", ");
        }
        query
            .push("updated_at = NOW() WHERE id = ")
            .push_bind(id)
            .push(" AND customer_id = ")
            .push_bind(identity.tenant_id)
            .push(" RETURNING *");
        let item = query.build_query_as::<Item>().fetch_one(&self.pool).await?;

        Ok(item)
    }

    async fn delete(&self, identity: &IdentityContext, id: Uuid) -> Result<(), AppError> {
        sqlx::query("DELETE FROM items WHERE id = $1 AND customer_id = $2")
            .bind(id)
            .bind(identity.tenant_id)
            .execute(&self.pool)
            .await?;
        Ok(())
    }
}

// Both count and row queries use the same tenant/filter predicates. Only fixed
// SQL fragments enter the builder; all external values remain bind parameters.
fn filtered_items_query(
    select: &'static str,
    identity: &IdentityContext,
    params: &ListParams,
) -> QueryBuilder<Postgres> {
    let mut query = QueryBuilder::new(select);
    query
        .push(" WHERE customer_id = ")
        .push_bind(identity.tenant_id);
    if let Some(ref status) = params.status {
        query.push(" AND status = ").push_bind(status);
    }
    if let Some(ref search) = params.search {
        let pattern = format!("%{search}%");
        query
            .push(" AND (name ILIKE ")
            .push_bind(pattern.clone())
            .push(" OR description ILIKE ")
            .push_bind(pattern)
            .push(")");
    }
    query
}
