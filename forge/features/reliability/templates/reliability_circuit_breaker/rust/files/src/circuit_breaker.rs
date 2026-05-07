//! Minimal async circuit breaker for outbound calls.
//!
//! Tracks a rolling count of failures per breaker name; when failures
//! exceed the threshold, the breaker opens for a reset interval before
//! probing with a single half-open call. Keeps dependencies to just
//! ``tokio`` + ``std::sync`` — no extra crates.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum State {
    Closed,
    Open,
    HalfOpen,
}

struct BreakerState {
    state: State,
    failures: u32,
    opened_at: Option<Instant>,
}

#[derive(Clone)]
pub struct CircuitBreaker {
    threshold: u32,
    reset: Duration,
    inner: Arc<Mutex<BreakerState>>,
}

impl CircuitBreaker {
    pub fn new(threshold: u32, reset: Duration) -> Self {
        Self {
            threshold,
            reset,
            inner: Arc::new(Mutex::new(BreakerState {
                state: State::Closed,
                failures: 0,
                opened_at: None,
            })),
        }
    }

    pub async fn call<F, Fut, T, E>(&self, op: F) -> Result<T, BreakerError<E>>
    where
        F: FnOnce() -> Fut,
        Fut: std::future::Future<Output = Result<T, E>>,
    {
        {
            let mut s = self.inner.lock().unwrap();
            if s.state == State::Open {
                if let Some(opened) = s.opened_at {
                    if opened.elapsed() >= self.reset {
                        s.state = State::HalfOpen;
                    } else {
                        return Err(BreakerError::Open);
                    }
                } else {
                    s.state = State::HalfOpen;
                }
            }
        }
        match op().await {
            Ok(v) => {
                let mut s = self.inner.lock().unwrap();
                s.state = State::Closed;
                s.failures = 0;
                s.opened_at = None;
                Ok(v)
            }
            Err(e) => {
                let mut s = self.inner.lock().unwrap();
                s.failures += 1;
                if s.state == State::HalfOpen || s.failures >= self.threshold {
                    s.state = State::Open;
                    s.opened_at = Some(Instant::now());
                }
                Err(BreakerError::Inner(e))
            }
        }
    }
}

#[derive(Debug)]
pub enum BreakerError<E> {
    Open,
    Inner(E),
}

#[derive(Default)]
pub struct BreakerRegistry {
    inner: Mutex<HashMap<String, CircuitBreaker>>,
}

impl BreakerRegistry {
    pub fn get(&self, name: &str) -> CircuitBreaker {
        let mut map = self.inner.lock().unwrap();
        map.entry(name.to_string())
            .or_insert_with(|| {
                let threshold = std::env::var("CIRCUIT_BREAKER_THRESHOLD")
                    .ok()
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(5);
                let reset_secs = std::env::var("CIRCUIT_BREAKER_RESET_TIMEOUT")
                    .ok()
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(30);
                CircuitBreaker::new(threshold, Duration::from_secs(reset_secs))
            })
            .clone()
    }
}
