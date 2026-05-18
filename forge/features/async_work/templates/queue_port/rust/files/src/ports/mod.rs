//! Capability ports — abstract surfaces concrete adapters implement.
//!
//! See `docs/rfcs/RFC-012-forgequeue-port.md` for the cross-language
//! contract; the `queue` module is the Rust sibling of the Python
//! `app.ports.queue` Protocol and the Node `app/ports/queue.ts`
//! interface.

pub mod queue;
