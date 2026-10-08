use crate::error_port::{ErrorPort, default::DefaultErrorPort};
use crate::errors::AppError;

#[test]
fn public_errors_keep_context_and_unknown_errors_are_redacted() {
    let adapter = DefaultErrorPort;
    for error in [
        AppError::not_found("Item", "one"),
        AppError::already_exists("Item", "one"),
        AppError::duplicate_entry("Item", "name", "one"),
        AppError::read_only("Item"),
        AppError::DependencyUnavailable {
            dependency: "upstream".into(),
        },
        AppError::AuthRequired,
    ] {
        let envelope = adapter.serialize(&error);
        assert_eq!(envelope.error.code, error.code().as_str());
        assert!(envelope.error.context.is_object());
    }
    for error in [
        Box::new(AppError::Internal("secret".into())) as Box<dyn std::error::Error>,
        Box::new(std::io::Error::other("secret")),
    ] {
        let envelope = adapter.serialize(error.as_ref());
        assert_eq!(envelope.error.code, "INTERNAL_ERROR");
        assert!(!envelope.error.message.contains("secret"));
    }
}
