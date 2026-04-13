/**
 * Auto-generated types from OpenAPI spec.
 *
 * In production, run `npm run codegen` with the backend running to regenerate.
 * This hand-written placeholder mirrors the FastAPI backend's domain models.
 */

// --- feature type definitions ---

export type HealthStatus = 'UP' | 'DOWN' | 'DEGRADED';

export interface ComponentStatus {
	status: HealthStatus;
	latency_ms: number | null;
	details: Record<string, unknown> | null;
}

export interface LivenessResponse {
	status: HealthStatus;
	details: string;
}

export interface ReadinessResponse {
	status: HealthStatus;
	components: Record<string, ComponentStatus>;
	system_info: Record<string, string>;
}

export interface InfoResponse {
	title: string;
	version: string;
	description: string;
}

export interface TaskEnqueueRequest {
	task_type: string;
	payload?: Record<string, unknown> | null;
	max_retries?: number;
}

export interface TaskEnqueueResponse {
	id: string;
	task_type: string;
	status: string;
}

export interface TaskStatusResponse {
	id: string;
	task_type: string;
	status: string;
	payload: Record<string, unknown> | null;
	result: Record<string, unknown> | null;
	error: string | null;
	attempts: number;
	max_retries: number;
	created_at: string | null;
	started_at: string | null;
	completed_at: string | null;
}

export interface LogLevelRequest {
	logger?: string;
	level: string;
}

export interface LogLevelResponse {
	logger: string;
	previous_level: string;
	current_level: string;
}

export interface ApiError {
	message: string;
	type: string;
	detail: Record<string, unknown> | null;
}
