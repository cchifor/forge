use sqlx::PgPool;
use uuid::Uuid;

use crate::errors::AppError;
use crate::middleware::tenant::TenantContext;
use crate::models::{CreateItem, Item, ListParams, PaginatedResponse, UpdateItem};

pub async fn list(
    pool: &PgPool,
    tenant: &TenantContext,
    params: ListParams,
) -> Result<PaginatedResponse<Item>, AppError> {
    let skip = params.skip.unwrap_or(0);
    let limit = params.limit.unwrap_or(20).min(100);

    // Build dynamic query — always scoped by customer_id
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

    // Build and execute count query
    let mut count_query = sqlx::query_scalar::<_, i64>(&count_sql);
    count_query = count_query.bind(tenant.customer_id);
    if let Some(ref status) = params.status {
        count_query = count_query.bind(status);
    }
    if let Some(ref search) = params.search {
        let pattern = format!("%{search}%");
        count_query = count_query.bind(pattern.clone()).bind(pattern);
    }
    let total = count_query.fetch_one(pool).await?;

    // Build and execute items query
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
    let items = items_query.fetch_all(pool).await?;

    Ok(PaginatedResponse {
        items,
        total,
        skip,
        limit,
        has_more: skip + limit < total,
    })
}

pub async fn create(
    pool: &PgPool,
    tenant: &TenantContext,
    data: CreateItem,
) -> Result<Item, AppError> {
    // Check for duplicate name within the same customer
    let existing = sqlx::query_scalar::<_, i64>(
        "SELECT COUNT(*) FROM items WHERE name = $1 AND customer_id = $2",
    )
    .bind(&data.name)
    .bind(tenant.customer_id)
    .fetch_one(pool)
    .await?;

    if existing > 0 {
        return Err(AppError::already_exists("Item", &data.name));
    }

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
    .fetch_one(pool)
    .await?;

    Ok(item)
}

pub async fn get_by_id(
    pool: &PgPool,
    tenant: &TenantContext,
    id: Uuid,
) -> Result<Item, AppError> {
    let item =
        sqlx::query_as::<_, Item>("SELECT * FROM items WHERE id = $1 AND customer_id = $2")
            .bind(id)
            .bind(tenant.customer_id)
            .fetch_optional(pool)
            .await?
            .ok_or_else(|| AppError::not_found("Item", id.to_string()))?;

    Ok(item)
}

pub async fn update(
    pool: &PgPool,
    tenant: &TenantContext,
    id: Uuid,
    data: UpdateItem,
) -> Result<Item, AppError> {
    // Ensure item exists and belongs to this tenant
    get_by_id(pool, tenant, id).await?;

    // Check for duplicate name if name is being updated
    if let Some(ref name) = data.name {
        let existing = sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM items WHERE name = $1 AND customer_id = $2 AND id != $3",
        )
        .bind(name)
        .bind(tenant.customer_id)
        .bind(id)
        .fetch_one(pool)
        .await?;

        if existing > 0 {
            return Err(AppError::already_exists("Item", name));
        }
    }

    // Build dynamic UPDATE query
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
        return get_by_id(pool, tenant, id).await;
    }

    sets.push("updated_at = NOW()".to_string());
    bind_idx += 1;
    let id_idx = bind_idx;

    let sql = format!(
        "UPDATE items SET {} WHERE id = ${id_idx} RETURNING *",
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
    query = query.bind(id);

    let item = query.fetch_one(pool).await?;
    Ok(item)
}

pub async fn delete(pool: &PgPool, tenant: &TenantContext, id: Uuid) -> Result<(), AppError> {
    // Ensure item exists and belongs to this tenant
    get_by_id(pool, tenant, id).await?;

    sqlx::query("DELETE FROM items WHERE id = $1 AND customer_id = $2")
        .bind(id)
        .bind(tenant.customer_id)
        .execute(pool)
        .await?;

    Ok(())
}
