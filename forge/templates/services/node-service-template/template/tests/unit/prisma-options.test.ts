import { describe, expect, it } from "vitest";
import { databaseConnectionOptions } from "../../src/lib/prisma-options.js";

describe("Prisma pg connection options without the optional pool feature", () => {
	it("preserves explicit pool settings, credentials, SSL and schema", () => {
		const options = databaseConnectionOptions(
			"postgres://user:pass@localhost/db?connection_limit=3&pool_timeout=2&sslmode=require&schema=tenant",
		);
		expect(options.max).toBe(3);
		expect(options.connectionTimeoutMillis).toBe(2000);
		const url = new URL(options.connectionString!);
		expect(url.username).toBe("user");
		expect(url.password).toBe("pass");
		expect(url.searchParams.get("sslmode")).toBe("require");
		expect(url.searchParams.get("schema")).toBe("tenant");
		expect(url.searchParams.has("connection_limit")).toBe(false);
		expect(url.searchParams.has("pool_timeout")).toBe(false);
	});

	it("keeps defaults when no pool parameters are configured", () => {
		expect(databaseConnectionOptions()).toEqual({
			connectionString: undefined,
			connectionTimeoutMillis: 5000,
		});
		expect(databaseConnectionOptions("postgres://localhost/db")).toEqual({
			connectionString: "postgres://localhost/db",
			connectionTimeoutMillis: 5000,
		});
		expect(
			databaseConnectionOptions("postgres://localhost/db?connection_limit=2"),
		).toMatchObject({ max: 2, connectionTimeoutMillis: 5000 });
	});

	it("preserves a disabled timeout and fractional seconds", () => {
		expect(
			databaseConnectionOptions("postgres://localhost/db?pool_timeout=0")
				.connectionTimeoutMillis,
		).toBe(0);
		expect(
			databaseConnectionOptions("postgres://localhost/db?pool_timeout=0.5")
				.connectionTimeoutMillis,
		).toBe(500);
	});

	it.each([
		"connection_limit=0",
		"connection_limit=-1",
		"connection_limit=2.5",
		"connection_limit=nope",
		"connection_limit=",
		"pool_timeout=-1",
		"pool_timeout=nope",
		"pool_timeout=Infinity",
		"pool_timeout=",
	])("rejects invalid pool parameters: %s", (query) => {
		expect(() =>
			databaseConnectionOptions(`postgres://localhost/db?${query}`),
		).toThrow();
	});
});
