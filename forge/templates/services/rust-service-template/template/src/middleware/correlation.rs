use axum::http::{HeaderName, HeaderValue, Request};
use tower_http::request_id::{
    MakeRequestId, PropagateRequestIdLayer, RequestId, SetRequestIdLayer,
};
use uuid::Uuid;

static X_REQUEST_ID: HeaderName = HeaderName::from_static("x-request-id");

#[derive(Clone)]
pub struct UuidRequestId;

impl MakeRequestId for UuidRequestId {
    fn make_request_id<B>(&mut self, _request: &Request<B>) -> Option<RequestId> {
        let id = Uuid::new_v4().to_string();
        Some(RequestId::new(HeaderValue::from_str(&id).unwrap()))
    }
}

pub fn set_request_id_layer() -> SetRequestIdLayer<UuidRequestId> {
    SetRequestIdLayer::new(X_REQUEST_ID.clone(), UuidRequestId)
}

pub fn propagate_request_id_layer() -> PropagateRequestIdLayer {
    PropagateRequestIdLayer::new(X_REQUEST_ID.clone())
}
