use reqwest::{Client, Response};
use serde::Serialize;

use crate::middleware::tenant::TenantContext;

/// Service-to-service HTTP client that automatically propagates tenant context
/// and correlation headers from the incoming request.
///
/// # Example
///
/// ```rust,ignore
/// let client = ServiceClient::new("http://notification:5001", "notification");
/// let resp = client.get("/api/v1/notifications", &tenant, correlation_id).await?;
/// ```
pub struct ServiceClient {
    base_url: String,
    service_name: String,
    client: Client,
}

impl ServiceClient {
    pub fn new(base_url: impl Into<String>, service_name: impl Into<String>) -> Self {
        Self {
            base_url: base_url.into(),
            service_name: service_name.into(),
            client: Client::new(),
        }
    }

    pub async fn get(
        &self,
        path: &str,
        tenant: &TenantContext,
        correlation_id: Option<&str>,
    ) -> Result<Response, reqwest::Error> {
        let req = self
            .client
            .get(format!("{}{}", self.base_url, path))
            .headers(self.build_headers(tenant, correlation_id));
        let resp = req.send().await?;
        Ok(resp)
    }

    pub async fn post<T: Serialize>(
        &self,
        path: &str,
        body: &T,
        tenant: &TenantContext,
        correlation_id: Option<&str>,
    ) -> Result<Response, reqwest::Error> {
        let resp = self
            .client
            .post(format!("{}{}", self.base_url, path))
            .headers(self.build_headers(tenant, correlation_id))
            .json(body)
            .send()
            .await?;
        Ok(resp)
    }

    fn build_headers(
        &self,
        tenant: &TenantContext,
        correlation_id: Option<&str>,
    ) -> reqwest::header::HeaderMap {
        let mut headers = reqwest::header::HeaderMap::new();

        // Propagate tenant context (Gatekeeper headers)
        headers.insert(
            "x-gatekeeper-user-id",
            tenant.user_id.to_string().parse().unwrap(),
        );
        headers.insert(
            "x-gatekeeper-email",
            tenant
                .email
                .parse()
                .unwrap_or_else(|_| reqwest::header::HeaderValue::from_static("")),
        );
        headers.insert(
            "x-gatekeeper-roles",
            tenant
                .roles
                .join(",")
                .parse()
                .unwrap_or_else(|_| reqwest::header::HeaderValue::from_static("")),
        );
        headers.insert(
            "x-customer-id",
            tenant.customer_id.to_string().parse().unwrap(),
        );

        // Propagate correlation ID
        if let Some(id) = correlation_id {
            if let Ok(val) = id.parse() {
                headers.insert("x-request-id", val);
            }
        }

        headers
    }
}
