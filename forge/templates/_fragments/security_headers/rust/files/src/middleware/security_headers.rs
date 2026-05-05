//! Security-headers middleware.
//!
//! Injects a conservative set of response headers on every response. Matches
//! the Python fragment's defaults: nosniff, frame DENY, strict referrer,
//! restrictive CSP, restrictive Permissions-Policy, and HSTS when served over
//! TLS (HSTS is omitted from plain-HTTP responses — browsers ignore it anyway).

use axum::body::Body;
use axum::http::{HeaderName, HeaderValue, Request};
use axum::middleware::Next;
use axum::response::Response;

const HEADERS: &[(&str, &str)] = &[
    ("x-content-type-options", "nosniff"),
    ("x-frame-options", "DENY"),
    ("referrer-policy", "strict-origin-when-cross-origin"),
    (
        "permissions-policy",
        "accelerometer=(), camera=(), geolocation=(), microphone=()",
    ),
    (
        "content-security-policy",
        "default-src 'self'; frame-ancestors 'none'",
    ),
];

pub async fn security_headers_middleware(req: Request<Body>, next: Next) -> Response {
    let is_https = req.uri().scheme_str() == Some("https");
    let mut response = next.run(req).await;
    let headers = response.headers_mut();
    for (name, value) in HEADERS {
        if let (Ok(h), Ok(v)) = (
            HeaderName::from_bytes(name.as_bytes()),
            HeaderValue::from_str(value),
        ) {
            headers.entry(h).or_insert(v);
        }
    }
    if is_https {
        headers
            .entry(HeaderName::from_static("strict-transport-security"))
            .or_insert(HeaderValue::from_static(
                "max-age=31536000; includeSubDomains",
            ));
    }
    response
}
