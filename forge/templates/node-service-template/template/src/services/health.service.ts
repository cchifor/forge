import { prisma } from "../lib/prisma.js";
import type { ComponentStatus } from "../schemas/health.schema.js";

export async function checkDatabase(): Promise<ComponentStatus> {
	const start = performance.now();
	try {
		await prisma.$queryRaw`SELECT 1`;
		return { status: "UP", latencyMs: Math.round(performance.now() - start) };
	} catch {
		return { status: "DOWN", latencyMs: null };
	}
}
