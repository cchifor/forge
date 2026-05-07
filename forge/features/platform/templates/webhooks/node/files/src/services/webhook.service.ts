/**
 * Webhook registry + HMAC-SHA256 delivery for Node/Fastify.
 *
 * In-memory registry in v1 — suitable for dev and single-replica prod. For
 * multi-replica deployments, swap the `registry` Map for a Prisma-backed
 * repository against a `webhooks` table (mirror the Python feature's
 * model shape).
 */

import { createHmac, randomBytes, randomUUID } from "node:crypto";

export interface Webhook {
	id: string;
	name: string;
	url: string;
	secret: string;
	events: string[];
	is_active: boolean;
	extra_headers: Record<string, string> | null;
	created_at: string;
}

export interface WebhookCreate {
	name: string;
	url: string;
	events?: string[];
	extra_headers?: Record<string, string>;
}

export interface DeliveryResult {
	webhook_id: string;
	status_code: number | null;
	ok: boolean;
	error: string | null;
	duration_ms: number;
}

const registry = new Map<string, Webhook>();

function generateSecret(): string {
	return randomBytes(32).toString("hex");
}

function matchesEvent(webhook: Webhook, event: string): boolean {
	if (!webhook.events || webhook.events.length === 0) return true;
	// glob-style suffix matching: "item.*" matches "item.created"
	return webhook.events.some((pattern) => {
		if (pattern === event) return true;
		if (pattern.endsWith("*")) {
			return event.startsWith(pattern.slice(0, -1));
		}
		return false;
	});
}

function sign(
	secret: string,
	timestamp: string,
	nonce: string,
	body: Buffer,
): string {
	return createHmac("sha256", secret)
		.update(timestamp)
		.update(".")
		.update(nonce)
		.update(".")
		.update(body)
		.digest("hex");
}

export function listWebhooks(): Webhook[] {
	return Array.from(registry.values()).sort((a, b) =>
		b.created_at.localeCompare(a.created_at),
	);
}

export function createWebhook(data: WebhookCreate): Webhook {
	const id = crypto.randomUUID();
	const webhook: Webhook = {
		id,
		name: data.name,
		url: data.url,
		secret: generateSecret(),
		events: data.events ?? [],
		is_active: true,
		extra_headers: data.extra_headers ?? null,
		created_at: new Date().toISOString(),
	};
	registry.set(id, webhook);
	return webhook;
}

export function getWebhook(id: string): Webhook | null {
	return registry.get(id) ?? null;
}

export function deleteWebhook(id: string): boolean {
	return registry.delete(id);
}

export async function deliver(
	webhook: Webhook,
	event: string,
	payload: unknown,
): Promise<DeliveryResult> {
	const start = performance.now();
	const timestamp = Math.floor(Date.now() / 1000).toString();
	const nonce = randomUUID().replace(/-/g, "");
	const body = Buffer.from(
		JSON.stringify({ event, data: payload }),
		"utf-8",
	);
	const signature = sign(webhook.secret, timestamp, nonce, body);

	const headers: Record<string, string> = {
		"Content-Type": "application/json",
		"X-Webhook-Signature": signature,
		"X-Webhook-Timestamp": timestamp,
		"X-Webhook-Nonce": nonce,
		"X-Webhook-Event": event,
		"X-Webhook-Id": webhook.id,
		...(webhook.extra_headers ?? {}),
	};

	const controller = new AbortController();
	const timeout = setTimeout(() => controller.abort(), 10000);
	try {
		const resp = await fetch(webhook.url, {
			method: "POST",
			headers,
			body,
			signal: controller.signal,
		});
		return {
			webhook_id: webhook.id,
			status_code: resp.status,
			ok: resp.ok,
			error: resp.ok ? null : `http ${resp.status}`,
			duration_ms: Math.round(performance.now() - start),
		};
	} catch (err: any) {
		return {
			webhook_id: webhook.id,
			status_code: null,
			ok: false,
			error: String(err?.message ?? err),
			duration_ms: Math.round(performance.now() - start),
		};
	} finally {
		clearTimeout(timeout);
	}
}

export async function fireEvent(
	event: string,
	payload: unknown,
): Promise<DeliveryResult[]> {
	const results: DeliveryResult[] = [];
	for (const webhook of registry.values()) {
		if (webhook.is_active && matchesEvent(webhook, event)) {
			results.push(await deliver(webhook, event, payload));
		}
	}
	return results;
}
