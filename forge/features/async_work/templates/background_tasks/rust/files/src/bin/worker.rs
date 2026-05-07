//! Worker binary — runs the Apalis job loop.
//!
//! Launch alongside the main service container:
//!     cargo run --bin worker
//!
//! The worker connects to the Redis queue pointed to by TASKIQ_BROKER_URL
//! and drains `HelloJob` messages. Add more workers by calling
//! `.register(...)` before `.run()` and pointing each at its job type.

use apalis::prelude::*;
use dotenvy::dotenv;
use tracing_subscriber::EnvFilter;

use api::worker::{handle_hello, storage, HelloJob};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    dotenv().ok();
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env().add_directive("info".parse().unwrap()))
        .json()
        .init();

    let hello_storage = storage::<HelloJob>().await?;

    tracing::info!("worker starting; awaiting jobs...");
    Monitor::new()
        .register(
            WorkerBuilder::new("hello-worker")
                .backend(hello_storage)
                .build_fn(handle_hello),
        )
        .run()
        .await?;
    Ok(())
}
