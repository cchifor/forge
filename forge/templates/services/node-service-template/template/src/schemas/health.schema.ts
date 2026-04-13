import { z } from "zod";

export const HealthStatus = z.enum(["UP", "DOWN", "DEGRADED"]);
export type HealthStatus = z.infer<typeof HealthStatus>;

export const LivenessResponse = z.object({
	status: HealthStatus,
	details: z.string(),
});
export type LivenessResponse = z.infer<typeof LivenessResponse>;

export const ComponentStatus = z.object({
	status: HealthStatus,
	latency_ms: z.number().nullable(),
});
export type ComponentStatus = z.infer<typeof ComponentStatus>;

export const ReadinessResponse = z.object({
	status: HealthStatus,
	components: z.record(ComponentStatus),
	system_info: z.record(z.string()),
});
export type ReadinessResponse = z.infer<typeof ReadinessResponse>;
