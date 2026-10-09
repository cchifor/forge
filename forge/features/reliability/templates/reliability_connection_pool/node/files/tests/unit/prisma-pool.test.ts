import { afterEach, expect, it, vi } from "vitest";

afterEach(() => {
	vi.unstubAllEnvs();
	vi.resetModules();
});

it("translates legacy URL pooling into Prisma 7 driver options", async () => {
	const { prismaPoolOptions } = await import("../../src/lib/prisma-pool.js");
	const options = prismaPoolOptions(
		"postgres://localhost/db?connection_limit=3&pool_timeout=2&sslmode=require",
	);
	expect(options.max).toBe(3);
	expect(options.connectionTimeoutMillis).toBe(2000);
	const url = new URL(options.connectionString!);
	expect(url.searchParams.get("sslmode")).toBe("require");
	expect(url.searchParams.has("connection_limit")).toBe(false);
	expect(url.searchParams.has("pool_timeout")).toBe(false);
});

it("rejects invalid driver pool limits instead of accepting unbounded settings", async () => {
	const { prismaPoolOptions } = await import("../../src/lib/prisma-pool.js");
	for (const query of [
		"connection_limit=0",
		"connection_limit=nope",
		"pool_timeout=-1",
	]) {
		expect(() =>
			prismaPoolOptions(`postgres://localhost/db?${query}`),
		).toThrow();
	}
});

it("adds bounded pool defaults without discarding database URL parameters", async () => {
	vi.stubEnv("PRISMA_CONNECTION_LIMIT", "20");
	vi.stubEnv("PRISMA_POOL_TIMEOUT", "10");
	const { databaseUrlWithPool } = await import("../../src/lib/prisma-pool.js");
	const url = new URL(
		databaseUrlWithPool("postgres://user:pass@localhost/db?schema=tenant"),
	);
	expect(url.searchParams.get("connection_limit")).toBe("20");
	expect(url.searchParams.get("pool_timeout")).toBe("10");
	expect(url.searchParams.get("schema")).toBe("tenant");
});

it("preserves explicit pool settings and applies environment defaults", async () => {
	vi.stubEnv("PRISMA_CONNECTION_LIMIT", "5");
	vi.stubEnv("PRISMA_POOL_TIMEOUT", "7");
	const { databaseUrlWithPool } = await import("../../src/lib/prisma-pool.js");
	const explicit = new URL(
		databaseUrlWithPool(
			"postgres://localhost/db?connection_limit=2&pool_timeout=3",
		),
	);
	expect(explicit.searchParams.get("connection_limit")).toBe("2");
	expect(explicit.searchParams.get("pool_timeout")).toBe("3");
	const defaults = new URL(databaseUrlWithPool("postgres://localhost/db"));
	expect(defaults.searchParams.get("connection_limit")).toBe("5");
	expect(defaults.searchParams.get("pool_timeout")).toBe("7");
	expect(() => databaseUrlWithPool("invalid")).toThrow();
});
