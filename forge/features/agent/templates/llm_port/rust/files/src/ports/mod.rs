//! Capability ports — abstract surfaces concrete adapters implement.
//!
//! The `llm` module is the Rust sibling of the Python
//! `app.ports.llm` Protocol and the Node `app/ports/llm.ts`
//! interface — see the TypeSpec contract at
//! `forge/templates/_shared/ports/llm/contract.tsp` for the
//! cross-language spec.
//!
//! NOTE: this file conflicts with `queue_port`'s and `cache_port`'s
//! `ports/mod.rs` in strict mode if more than one of those ports is
//! enabled on the same Rust backend. Co-existence on Rust requires the
//! Pillar A.4 `PortSpec` mechanism rendering a single shared
//! `ports/mod.rs`; today, the `conflicts_with` declaration on the
//! `llm_port` fragment makes the resolver fail loudly at plan-build
//! time rather than silently corrupting the generated tree. Python
//! and Node have no equivalent constraint.

pub mod llm;
