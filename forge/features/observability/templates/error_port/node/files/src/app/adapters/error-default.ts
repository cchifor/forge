/**
 * Default error-port adapter — RFC-007 envelope shape.
 *
 * Bridges the existing `lib/errors.ts` machinery (the `AppError` class
 * hierarchy + `statusForCode` map already shipping with the base
 * template) to the new `ErrorPort` interface. The adapter is a thin
 * wrapper — all the real work (status lookup, context surfacing) lives
 * in `lib/errors.ts` and this adapter just composes the object the
 * port contract requires.
 *
 * Plugins shipping custom envelopes implement `ErrorPort` themselves
 * and register their class in place of this one (via the project's
 * dependency-injection container).
 */

import { AppError } from "../../lib/errors.js";

import type { ErrorEnvelope, ErrorPort } from "../ports/error-port.js";

/**
 * The reference adapter — emits the canonical RFC-007 envelope.
 *
 * For known `AppError` subclasses, surfaces the registered `code` and
 * structured `context`. For everything else, falls back to
 * `INTERNAL_ERROR` with a redacted message — the central error
 * middleware logs the real exception so operators can correlate via
 * `correlation_id`.
 */
export class DefaultErrorPort implements ErrorPort {
	serialize(exc: unknown): ErrorEnvelope {
		if (exc instanceof AppError) {
			return {
				error: {
					code: exc.code,
					message: exc.message,
					type: exc.name,
					context: exc.context,
					correlation_id: "",
				},
			};
		}
		const type = exc instanceof Error ? exc.constructor.name : "UnknownError";
		return {
			error: {
				code: "INTERNAL_ERROR",
				// Redact the original message — the central middleware logs
				// the real exception alongside the correlation id.
				message: "An unexpected error occurred",
				type,
				context: {},
				correlation_id: "",
			},
		};
	}
}
