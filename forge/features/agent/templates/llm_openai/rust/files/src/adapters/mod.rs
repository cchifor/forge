//! Concrete adapters that implement capability ports declared in
//! `crate::ports`. See the TypeSpec LLM contract at
//! `forge/templates/_shared/ports/llm/contract.tsp` for the
//! cross-language port spec.
//!
//! NOTE: this file conflicts with `queue_apalis`'s and
//! `cache_memory`/`cache_redis`'s `adapters/mod.rs` in strict mode if
//! more than one of those adapters is enabled on the same Rust
//! backend. Co-existence on Rust requires the Pillar A.4 `PortSpec`
//! mechanism rendering a single shared `adapters/mod.rs`; today, the
//! `conflicts_with` declaration on the `llm_openai` fragment makes
//! the resolver fail loudly at plan-build time rather than silently
//! corrupting the generated tree.

pub mod llm_openai;
