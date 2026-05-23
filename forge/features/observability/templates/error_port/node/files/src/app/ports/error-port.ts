/**
 * Error port — capability contract for RFC-007 error-envelope serialisation.
 *
 * Promotes the hand-written error-handler code already shipping in the
 * base template (`src/lib/errors.ts` + `src/middleware/error-handler.ts`)
 * into a swappable port. The base template's central error middleware
 * keeps emitting the envelope as-is (that's the default behaviour);
 * plugins shipping custom envelope shapes implement `ErrorPort` and
 * register their adapter in place of `DefaultErrorPort`.
 *
 * The port surface is intentionally tiny — one `serialize` method that
 * takes an exception and returns the JSON-ready envelope object. HTTP
 * status, logging, and correlation-id propagation stay in the central
 * error middleware; the port owns only the wire shape. See
 * `docs/rfcs/RFC-007-error-contract.md` for the canonical envelope spec
 * and the cross-language port siblings:
 *
 * - Python: `src/app/ports/error_port.py`
 * - Rust:   `src/ports/error_port.rs`
 *
 * Adapters that mint custom codes (or change context shape) MUST keep
 * the top-level `{ error: {...} }` wrapper and the five required
 * fields (`code`, `message`, `type`, `context`, `correlation_id`);
 * otherwise the unified frontend client breaks. New `code` enum values
 * go through `registerErrorCode` so two features can't silently claim
 * the same mapping.
 */

/** The RFC-007 envelope returned by every `ErrorPort.serialize` call. */
export interface ErrorEnvelope {
	error: {
		/** RFC-007 enum, machine-readable, stable across versions. */
		code: string;
		/** Human-readable, UI-safe. Never contains stack or PII. */
		message: string;
		/** Concrete error class name — for diagnostic UIs / support tickets. */
		type: string;
		/** Freeform structured data; empty object when not applicable. */
		context: Record<string, unknown>;
		/**
		 * Request correlation id — echoes `X-Correlation-Id`. Adapters
		 * with no request context return an empty string; the central
		 * error middleware fills it in.
		 */
		correlation_id: string;
	};
}

/**
 * Serialise a raised exception into the RFC-007 envelope.
 *
 * Implementations are pure — they MUST NOT mutate the exception or
 * perform I/O. The central error middleware calls `serialize` once per
 * request, then writes the returned object as the response body with
 * the matching HTTP status (mapped via `statusForCode`).
 */
export interface ErrorPort {
	serialize(exc: unknown): ErrorEnvelope;
}
