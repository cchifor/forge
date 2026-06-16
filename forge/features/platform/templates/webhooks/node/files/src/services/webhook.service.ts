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

export class WebhookUrlError extends Error {}

/**
 * Reject webhook targets that point at internal/non-public hosts (SSRF) or use
 * a non-http(s) scheme. Mirrors the Python feature's `validate_outbound_url`.
 *
 * Host literals in loopback / link-local (incl. the 169.254.169.254 cloud
 * metadata endpoint) / RFC1918 private ranges are blocked. DNS names are not
 * resolved here (no sync resolver in the fetch path); pair this pre-flight
 * check with `redirect: "manual"` below so a 3xx to an internal host cannot
 * slip past it.
 */
function validateOutboundUrl(rawUrl: string): void {
	let parsed: URL;
	try {
		parsed = new URL(rawUrl);
	} catch {
		throw new WebhookUrlError(`invalid webhook URL: ${rawUrl}`);
	}
	const scheme = parsed.protocol.toLowerCase();
	if (scheme !== "https:" && scheme !== "http:") {
		throw new WebhookUrlError(`unsupported URL scheme ${scheme}; use https`);
	}
	// `hostname` strips brackets from IPv6 literals; lowercase for name checks.
	const host = parsed.hostname.toLowerCase();
	if (!host) {
		throw new WebhookUrlError("webhook URL has no host");
	}
	if (isBlockedHost(host)) {
		throw new WebhookUrlError(`${host} is a non-public address; refused`);
	}
}

function isBlockedHost(host: string): boolean {
	if (host === "localhost" || host.endsWith(".localhost")) return true;
	// IPv6 literals: loopback (::1), unspecified (::), link-local (fe80::/10),
	// unique-local (fc00::/7), and IPv4-mapped loopback (::ffff:127.0.0.1).
	if (host.includes(":")) {
		if (host === "::1" || host === "::") return true;
		if (host.startsWith("fe8") || host.startsWith("fe9")) return true;
		if (host.startsWith("fea") || host.startsWith("feb")) return true;
		if (host.startsWith("fc") || host.startsWith("fd")) return true;
		const mapped = host.split(":").pop() ?? "";
		if (mapped.includes(".")) return isBlockedIPv4(mapped);
		return false;
	}
	if (isBlockedIPv4(host)) return true;
	return false;
}

function isBlockedIPv4(host: string): boolean {
	const parts = host.split(".");
	if (parts.length !== 4) return false;
	const octets = parts.map((p) => Number(p));
	if (octets.some((n) => !Number.isInteger(n) || n < 0 || n > 255)) {
		return false;
	}
	const [a, b] = octets;
	if (a === 127) return true; // loopback 127.0.0.0/8
	if (a === 10) return true; // RFC1918 10.0.0.0/8
	if (a === 192 && b === 168) return true; // RFC1918 192.168.0.0/16
	if (a === 172 && b >= 16 && b <= 31) return true; // RFC1918 172.16.0.0/12
	if (a === 169 && b === 254) return true; // link-local 169.254.0.0/16 (metadata)
	if (a === 0) return true; // 0.0.0.0/8 unspecified
	return false;
}

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

	// Fast pre-flight SSRF reject (scheme + host literal). Paired with
	// `redirect: "manual"` below so a 3xx to an internal host can't bypass it.
	try {
		validateOutboundUrl(webhook.url);
	} catch (err: any) {
		return {
			webhook_id: webhook.id,
			status_code: null,
			ok: false,
			error: `refused: ${String(err?.message ?? err)}`,
			duration_ms: Math.round(performance.now() - start),
		};
	}

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
			// Do not auto-follow 3xx: a redirect to an internal host would
			// bypass the validateOutboundUrl pre-flight check above.
			redirect: "manual",
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
