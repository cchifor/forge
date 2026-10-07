import { expect, it } from "vitest";
import { buildApp } from "../../src/app.js";
import { prisma } from "../../src/lib/prisma.js";

it("readiness queries a real PostgreSQL database", async () => {
	if (!process.env.DATABASE_URL) throw new Error("Integration tests require DATABASE_URL");
	const app = await buildApp();
	try {
		const response = await app.inject({ method: "GET", url: "/api/v1/health/ready" });
		expect(response.statusCode).toBe(200);
		expect(response.json().status).toBe("UP");
	} finally {
		await app.close();
		await prisma.$disconnect();
	}
});
