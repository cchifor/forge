// Chat attachment upload helper — wraps ``POST /api/v1/chat-files``.
//
// The backend route accepts multipart `file` + optional `customer_id`,
// returns ``{id, filename, mime_type, size_bytes, storage_path}``.
// We surface only the fields ``AiChatInput.svelte`` renders as a chip.
//
// Pillar G.1 of the architectural improvement plan: before this file
// existed, the Paperclip button in ``AiChatInput.svelte`` was
// ``disabled`` and no UI path uploaded attachments, even though the
// generated FastAPI backend has a fully working ``chat-files`` router
// + storage + database table from the ``chat.attachments`` option.
// Agents could read uploaded files via ``GET /api/v1/chat-files/{id}``
// once they exist, but no user could create them through the chat UI.
//
// TODO(post-pub-of-canvas-core): if Pillar B Phase 3's template rewrite
// lands, this helper moves into ``@forge/canvas-svelte`` so all three
// stacks share one implementation. Until then it's a small local file.

import type { ChatAttachment } from '../chat.types';

interface UploadResponse {
	id: string;
	filename?: string;
	mime_type?: string;
	size_bytes?: number;
	storage_path?: string;
}

export class ChatAttachmentUploadError extends Error {
	readonly status: number;
	readonly detail: string;
	constructor(message: string, status: number, detail: string) {
		super(message);
		this.name = 'ChatAttachmentUploadError';
		this.status = status;
		this.detail = detail;
	}
}

/**
 * Upload one file and return the chip-ready metadata. Throws
 * ``ChatAttachmentUploadError`` on non-2xx so the caller can surface
 * a typed error to the user instead of swallowing it silently.
 *
 * ``customerId`` is forwarded as the multipart ``customer_id`` field.
 * When omitted, the backend uses the ``_ANON_CUSTOMER`` UUID — fine
 * for dev / single-tenant deployments; production multi-tenant
 * deployments should pass the authenticated user's customer id.
 *
 * ``fetch`` is injectable for tests (defaults to ``globalThis.fetch``).
 */
export async function uploadChatAttachment(
	file: File,
	options: {
		baseUrl?: string;
		customerId?: string;
		bearerToken?: string;
		fetch?: typeof globalThis.fetch;
	} = {}
): Promise<ChatAttachment> {
	const fetchFn = options.fetch ?? globalThis.fetch.bind(globalThis);
	const baseUrl = options.baseUrl ?? '';
	const form = new FormData();
	form.append('file', file);
	if (options.customerId) form.append('customer_id', options.customerId);

	const headers: Record<string, string> = {};
	if (options.bearerToken) headers.Authorization = `Bearer ${options.bearerToken}`;

	const url = (baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl) + '/api/v1/chat-files';
	const response = await fetchFn(url, {
		method: 'POST',
		body: form,
		headers
	});
	if (!response.ok) {
		const detail = await safeReadText(response);
		throw new ChatAttachmentUploadError(
			`Chat file upload failed (status ${response.status}): ${detail}`,
			response.status,
			detail
		);
	}
	const payload = (await response.json()) as UploadResponse;
	if (typeof payload.id !== 'string' || payload.id === '') {
		throw new ChatAttachmentUploadError(
			'Chat file upload returned no id',
			response.status,
			JSON.stringify(payload)
		);
	}
	return {
		id: payload.id,
		filename: payload.filename ?? file.name,
		mime_type: payload.mime_type ?? file.type ?? undefined,
		size_bytes: payload.size_bytes ?? file.size
	};
}

async function safeReadText(res: Response): Promise<string> {
	try {
		return await res.text();
	} catch {
		return '<no body>';
	}
}
