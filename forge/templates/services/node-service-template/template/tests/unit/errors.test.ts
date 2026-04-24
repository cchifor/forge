import { describe, it, expect } from "vitest";
import {
	AppError,
	NotFoundError,
	AlreadyExistsError,
	ValidationError,
	AuthRequiredError,
	PermissionDeniedError,
	DuplicateEntryError,
	DatabaseTimeoutError,
	registerErrorCode,
	statusForCode,
} from "../../src/lib/errors.js";

describe("AppError base", () => {
	it("derives statusCode from the canonical code map", () => {
		const err = new AppError("INTERNAL_ERROR", "Boom");
		expect(err.statusCode).toBe(500);
		expect(err.code).toBe("INTERNAL_ERROR");
		expect(err.context).toEqual({});
		expect(err.name).toBe("AppError");
	});

	it("accepts an explicit statusCode override", () => {
		const err = new AppError("INVALID_INPUT", "Bad", { statusCode: 418 });
		expect(err.statusCode).toBe(418);
	});

	it("carries structured context", () => {
		const err = new AppError("VALIDATION_FAILED", "x", {
			context: { field: "email" },
		});
		expect(err.context).toEqual({ field: "email" });
	});
});

describe("Specific error classes", () => {
	it("NotFoundError emits NOT_FOUND with entity/id context", () => {
		const err = new NotFoundError("Item", "abc-123");
		expect(err.code).toBe("NOT_FOUND");
		expect(err.statusCode).toBe(404);
		expect(err.context).toEqual({ entity: "Item", id: "abc-123" });
		expect(err).toBeInstanceOf(AppError);
	});

	it("AlreadyExistsError emits ALREADY_EXISTS", () => {
		const err = new AlreadyExistsError("Item", "dup");
		expect(err.code).toBe("ALREADY_EXISTS");
		expect(err.statusCode).toBe(409);
		expect(err.context).toEqual({ entity: "Item", name: "dup" });
	});

	it("ValidationError emits VALIDATION_FAILED", () => {
		const err = new ValidationError("Bad input", { field: "email" });
		expect(err.code).toBe("VALIDATION_FAILED");
		expect(err.statusCode).toBe(422);
		expect(err.context).toEqual({ field: "email" });
	});

	it("AuthRequiredError emits AUTH_REQUIRED 401", () => {
		const err = new AuthRequiredError();
		expect(err.code).toBe("AUTH_REQUIRED");
		expect(err.statusCode).toBe(401);
	});

	it("PermissionDeniedError emits PERMISSION_DENIED 403", () => {
		const err = new PermissionDeniedError();
		expect(err.code).toBe("PERMISSION_DENIED");
		expect(err.statusCode).toBe(403);
	});

	it("DuplicateEntryError carries field/value context", () => {
		const err = new DuplicateEntryError("Item", "name", "dup");
		expect(err.code).toBe("DUPLICATE_ENTRY");
		expect(err.statusCode).toBe(409);
		expect(err.context).toEqual({ entity: "Item", field: "name", value: "dup" });
	});

	it("DatabaseTimeoutError emits 503 DATABASE_TIMEOUT", () => {
		const err = new DatabaseTimeoutError();
		expect(err.code).toBe("DATABASE_TIMEOUT");
		expect(err.statusCode).toBe(503);
	});
});

describe("registerErrorCode", () => {
	it("allows registering a fragment-owned code", () => {
		registerErrorCode("QUOTA_EXCEEDED", 429);
		expect(statusForCode("QUOTA_EXCEEDED")).toBe(429);
	});

	it("is idempotent for identical registrations", () => {
		registerErrorCode("QUOTA_EXCEEDED", 429);
		registerErrorCode("QUOTA_EXCEEDED", 429);
		expect(statusForCode("QUOTA_EXCEEDED")).toBe(429);
	});

	it("throws on conflicting registration", () => {
		expect(() => registerErrorCode("QUOTA_EXCEEDED", 402)).toThrow(
			/already registered with status 429/,
		);
	});

	it("returns 500 for unknown codes", () => {
		expect(statusForCode("TOTALLY_MADE_UP")).toBe(500);
	});
});
