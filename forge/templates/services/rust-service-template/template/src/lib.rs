// Generated scaffolding ships with infrastructure (config loaders, error
// variants, service-client helpers) ready for user code that may not exist
// yet. The CI lane runs ``cargo clippy --all-targets -- -D warnings`` which
// promotes every default-enabled clippy lint to a hard error; the
// scaffolding inevitably trips a handful (dead_code, pedantic style nits)
// on day one. Silence them crate-wide so the lane can pass on a fresh
// generation, then drop or narrow these allows as your service fills in.
#![allow(dead_code)]
#![allow(clippy::needless_pass_by_value)]
#![allow(clippy::too_many_arguments)]
#![allow(clippy::module_name_repetitions)]
#![allow(clippy::missing_errors_doc)]
#![allow(clippy::missing_panics_doc)]
#![allow(clippy::must_use_candidate)]
#![allow(clippy::collapsible_if)]
#![allow(clippy::derivable_impls)]

pub mod app;
pub mod client;
pub mod config;
pub mod data;
pub mod db;
pub mod errors;
pub mod middleware;
pub mod models;
pub mod routes;
pub mod services;
// FORGE:LIB_MOD_REGISTRATION
// FORGE:BEGIN reliability_connection_pool:LIB_MOD_REGISTRATION
pub mod db_pool;
// FORGE:END reliability_connection_pool:LIB_MOD_REGISTRATION
