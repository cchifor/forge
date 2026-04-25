//! Repository abstractions over sqlx.
//!
//! Each entity ships a `*Repository` trait describing its persistence
//! contract plus a sqlx-backed implementation. Service-layer code
//! depends on the trait, not on raw queries — this lets unit tests
//! substitute an in-memory implementation without spinning up
//! Postgres, and gives operators a single seam to swap database
//! drivers without rewriting business logic.
//!
//! Implementations are responsible for scoping every query by
//! `tenant.customer_id`. The trait surface intentionally takes
//! `&TenantContext` on every method to make accidental tenant bypass
//! impossible at compile time.

pub mod item_repository;

pub use item_repository::{ItemRepository, PgItemRepository};
