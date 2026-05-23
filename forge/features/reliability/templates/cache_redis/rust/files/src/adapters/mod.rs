//! Concrete adapters that implement capability ports declared in
//! `crate::ports`.
//!
//! NOTE: this file conflicts with `queue_apalis`'s `adapters/mod.rs` in
//! strict mode. Co-existence on Rust requires the Pillar A.4
//! `PortSpec` mechanism; today, enable either the cache adapter OR
//! `queue_apalis` on a single Rust backend, not both.

pub mod cache_redis;
