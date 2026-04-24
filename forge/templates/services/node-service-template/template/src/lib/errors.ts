/**
 * RFC-007 error contract for the Node backend.
 *
 * Every error surfaced to HTTP clients is serialized into the canonical
 * envelope by `src/middleware/error-handler.ts`:
 *
 *     {
 *       "error": {
 *         "code": "NOT_FOUND",
 *         "message": "Item 'abc' not found",
 *         "type": "NotFoundError",
 *         "context": {},
 *         "correlation_id": "01H..."
 *       }
 *     }
 *
 * Fragments that need their own error code must call `registerErrorCode`
 * at module-import time. Re-registering a code with a different status
 * throws so two features cannot silently claim the same code.
 */

export type ErrorCode =
	| "AUTH_REQUIRED"
	| "PERMISSION_DENIED"
	| "READ_ONLY"
	| "NOT_FOUND"
	| "ALREADY_EXISTS"
	| "DUPLICATE_ENTRY"
	| "FOREIGN_KEY_VIOLATION"
	| "CONSTRAINT_VIOLATION"
	| "VALIDATION_FAILED"
	| "INVALID_INPUT"
	| "RATE_LIMITED"
	| "INTERNAL_ERROR"
	| "DATABASE_UNAVAILABLE"
	| "DATABASE_TIMEOUT"
	| "DEPENDENCY_UNAVAILABLE"
	| (string & { readonly __brand: "custom" });

const ERROR_CODE_STATUS: Map<string, number> = new Map([
	["AUTH_REQUIRED", 401],
	["PERMISSION_DENIED", 403],
	["READ_ONLY", 403],
	["NOT_FOUND", 404],
	["ALREADY_EXISTS", 409],
	["DUPLICATE_ENTRY", 409],
	["FOREIGN_KEY_VIOLATION", 409],
	["CONSTRAINT_VIOLATION", 409],
	["VALIDATION_FAILED", 422],
	["INVALID_INPUT", 422],
	["RATE_LIMITED", 429],
	["INTERNAL_ERROR", 500],
	["DATABASE_UNAVAILABLE", 503],
	["DATABASE_TIMEOUT", 503],
	["DEPENDENCY_UNAVAILABLE", 503],
]);

export function registerErrorCode(code: string, statusCode: number): void {
	const existing = ERROR_CODE_STATUS.get(code);
	if (existing !== undefined && existing !== statusCode) {
		throw new Error(
			`Error code "${code}" already registered with status ${existing}; ` +
				`refusing re-register as ${statusCode}.`,
		);
	}
	ERROR_CODE_STATUS.set(code, statusCode);
}

export function statusForCode(code: string): number {
	return ERROR_CODE_STATUS.get(code) ?? 500;
}

export class AppError extends Error {
	public readonly code: ErrorCode;
	public readonly statusCode: number;
	public readonly context: Record<string, unknown>;

	constructor(
		code: ErrorCode,
		message: string,
		options?: { statusCode?: number; context?: Record<string, unknown> },
	) {
		super(message);
		this.name = this.constructor.name;
		this.code = code;
		this.statusCode = options?.statusCode ?? statusForCode(code);
		this.context = options?.context ?? {};
	}
}

export class NotFoundError extends AppError {
	constructor(entity: string, id: string) {
		super("NOT_FOUND", `${entity} '${id}' not found`, {
			context: { entity, id },
		});
	}
}

export class AlreadyExistsError extends AppError {
	constructor(entity: string, name: string) {
		super("ALREADY_EXISTS", `${entity} '${name}' already exists`, {
			context: { entity, name },
		});
	}
}

export class ValidationError extends AppError {
	constructor(message: string, context: Record<string, unknown> = {}) {
		super("VALIDATION_FAILED", message, { context });
	}
}

export class AuthRequiredError extends AppError {
	constructor(message = "Authentication required") {
		super("AUTH_REQUIRED", message);
	}
}

export class PermissionDeniedError extends AppError {
	constructor(message = "You do not have permission to perform this action") {
		super("PERMISSION_DENIED", message);
	}
}

export class ReadOnlyError extends AppError {
	constructor(resource: string, id?: string) {
		const message = id
			? `${resource} '${id}' is read-only`
			: `${resource} is read-only`;
		super("READ_ONLY", message, { context: { resource, id } });
	}
}

export class DuplicateEntryError extends AppError {
	constructor(entity: string, field: string, value: unknown) {
		super(
			"DUPLICATE_ENTRY",
			`Duplicate ${entity}: ${field}='${String(value)}' already exists`,
			{ context: { entity, field, value } },
		);
	}
}

export class DatabaseTimeoutError extends AppError {
	constructor(message = "Database operation timed out") {
		super("DATABASE_TIMEOUT", message);
	}
}

export class DatabaseUnavailableError extends AppError {
	constructor(message = "Database is unavailable") {
		super("DATABASE_UNAVAILABLE", message);
	}
}

export class DependencyUnavailableError extends AppError {
	constructor(dependency: string, message?: string) {
		super(
			"DEPENDENCY_UNAVAILABLE",
			message ?? `${dependency} is unavailable`,
			{ context: { dependency } },
		);
	}
}
