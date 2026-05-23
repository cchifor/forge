/// Typed exception carrying the RFC-007 error envelope fields.
///
/// RFC-007 (`docs/rfcs/RFC-007-error-contract.md`) defines the canonical
/// error response body emitted by every forge-generated backend:
///
/// ```json
/// {
///   "error": {
///     "code": "NOT_FOUND",
///     "message": "Item 'abc-123' not found",
///     "type": "NotFoundError",
///     "context": {},
///     "correlation_id": "01H..."
///   }
/// }
/// ```
///
/// Before this class, Flutter clients collapsed every backend error to
/// `DioException.message`, losing the machine-readable `code`, the
/// structured `context`, and the correlation id that lets oncall join
/// a user-visible failure back to log lines.
///
/// The interceptor at `lib/src/api/client/error_interceptor.dart`
/// constructs an [AppException] whenever the response body matches the
/// envelope shape (top-level `error` key wrapping a map that has at
/// least `code` and `message`). When the shape doesn't match — bare
/// `{message: ...}`, framework-default bodies, network-level failures
/// — the interceptor falls back to the existing
/// `lib/src/core/errors/app_exception.dart` sealed family.
///
/// RFC-011 acceptance (1.2.0) introduces this class; see
/// `docs/rfcs/RFC-011-frontend-api-client-survey.md` for the rationale
/// (Vue/Svelte already get the envelope via TanStack-Query intercept
/// hooks; this closes the parity gap on Flutter without rewriting the
/// Retrofit + Riverpod toolchain).
class AppException implements Exception {
  const AppException({
    required this.code,
    required this.message,
    this.type,
    this.context = const <String, dynamic>{},
    this.correlationId,
    this.statusCode,
  });

  /// Machine-readable, stable error code from RFC-007 (e.g.
  /// `NOT_FOUND`, `VALIDATION_FAILED`, `RATE_LIMITED`). Use this to
  /// branch in UIs — `message` is for display only.
  final String code;

  /// Human-readable message safe to surface in UI. Never contains
  /// stack traces or PII per the RFC-007 server contract.
  final String message;

  /// Concrete server-side error class name (for diagnostic UIs /
  /// support tickets). Optional because some backends omit it on
  /// generic errors.
  final String? type;

  /// Freeform structured data, e.g. `{"field": "email"}` for a
  /// validation failure. Always a map; defaults to `{}` when the
  /// server omits it.
  final Map<String, dynamic> context;

  /// Request correlation id (echoes the `X-Correlation-Id` header or
  /// the server-assigned one). Enables log-join from the client.
  final String? correlationId;

  /// HTTP status code from the underlying response, when available.
  /// Not part of the envelope itself; kept for callers that want to
  /// distinguish e.g. `INVALID_INPUT` at 422 vs 409.
  final int? statusCode;

  /// Parse an [AppException] from a decoded JSON body, returning
  /// `null` when the body does not match the RFC-007 envelope shape.
  ///
  /// The envelope requires a top-level `error` key that is itself a
  /// map containing at least `code` (string) and `message` (string).
  /// Bodies that lack either field — bare `{message: "..."}`,
  /// Fastify's `{statusCode, error, message}`, Axum's `String`,
  /// FastAPI's default `{detail: "..."}` — fall through to `null`
  /// so the interceptor can apply its legacy fallback.
  static AppException? tryFromEnvelope(
    Object? body, {
    int? statusCode,
  }) {
    if (body is! Map) {
      return null;
    }
    final envelope = body['error'];
    if (envelope is! Map) {
      return null;
    }
    final code = envelope['code'];
    final message = envelope['message'];
    if (code is! String || message is! String) {
      return null;
    }
    final type = envelope['type'];
    final correlationId = envelope['correlation_id'];
    final rawContext = envelope['context'];
    final context = <String, dynamic>{};
    if (rawContext is Map) {
      for (final entry in rawContext.entries) {
        final key = entry.key;
        if (key is String) {
          context[key] = entry.value;
        }
      }
    }
    return AppException(
      code: code,
      message: message,
      type: type is String ? type : null,
      context: context,
      correlationId: correlationId is String ? correlationId : null,
      statusCode: statusCode,
    );
  }

  @override
  String toString() {
    final parts = <String>['AppException($code: $message'];
    if (type != null) parts.add('type=$type');
    if (statusCode != null) parts.add('status=$statusCode');
    if (correlationId != null) parts.add('correlation_id=$correlationId');
    if (context.isNotEmpty) parts.add('context=$context');
    return '${parts.join(', ')})';
  }
}
