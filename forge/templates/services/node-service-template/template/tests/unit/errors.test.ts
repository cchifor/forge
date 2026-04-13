import { describe, it, expect } from "vitest";
import { AppError, NotFoundError, AlreadyExistsError, ValidationError } from "../../src/lib/errors.js";

describe("Error classes", () => {
	it("NotFoundError has status 404", () => {
		const err = new NotFoundError("Item", "abc-123");
		expect(err.statusCode).toBe(404);
		expect(err.message).toContain("Item");
		expect(err.message).toContain("abc-123");
		expect(err).toBeInstanceOf(AppError);
	});

	it("AlreadyExistsError has status 409", () => {
		const err = new AlreadyExistsError("Item", "my-item");
		expect(err.statusCode).toBe(409);
		expect(err.message).toContain("Item");
		expect(err.message).toContain("my-item");
		expect(err).toBeInstanceOf(AppError);
	});

	it("ValidationError has status 422", () => {
		const err = new ValidationError("Bad input");
		expect(err.statusCode).toBe(422);
		expect(err.message).toBe("Bad input");
		expect(err).toBeInstanceOf(AppError);
	});

	it("AppError has correct name", () => {
		const err = new AppError(500, "Server error");
		expect(err.name).toBe("AppError");
		expect(err.statusCode).toBe(500);
	});
});
