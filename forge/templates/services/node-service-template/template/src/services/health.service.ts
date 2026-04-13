import { prisma } from "../lib/prisma.js";
import type { ComponentStatus } from "../schemas/health.schema.js";

export async function checkDatabase(): Promise<ComponentStatus> {
	const start = performance.now();
	try {
		await prisma.$queryRaw`SELECT 1`;
		return { status: "UP", latency_ms: Math.round(performance.now() - start) };
	} catch {
		return { status: "DOWN", latency_ms: null };
	}
}
