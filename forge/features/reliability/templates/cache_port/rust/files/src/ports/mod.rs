//! Capability ports — abstract surfaces concrete adapters implement.
//!
//! The `cache` module is the Rust sibling of the Python
//! `app.ports.cache` Protocol and the Node `app/ports/cache.ts`
//! interface.
//!
//! NOTE: this file conflicts with `queue_port`'s `ports/mod.rs` in
//! strict mode if both ports are enabled on the same Rust backend.
//! Co-existence on Rust requires the Pillar A.4 `PortSpec` mechanism;
//! today, enable cache_port OR queue_port on Rust, not both. Python
//! and Node have no equivalent constraint.

pub mod cache;
