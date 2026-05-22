// Chat attachment upload helper — wraps `POST /api/v1/chat-files`.
//
// The backend route accepts multipart `file` + optional `customer_id`,
// returns `{id, filename, mime_type, size_bytes, storage_path}`. We
// surface only the fields the AiChat input renders as a chip.
//
// Pillar G.1 (Vue half) of the architectural improvement plan. Mirror
// of the Svelte equivalent at
// `forge/templates/apps/svelte-frontend-template/.../chat-attachments.ts`.
// Both implementations are byte-equivalent in algorithm so the future
// `@forge/canvas-*` move (Pillar B Phase 3) is mechanical.

import { ref } from 'vue'

export interface ChatAttachment {
  id: string
  filename: string
  mime_type?: string
  size_bytes?: number
}

interface UploadResponse {
  id: string
  filename?: string
  mime_type?: string
  size_bytes?: number
  storage_path?: string
}

export class ChatAttachmentUploadError extends Error {
  readonly status: number
  readonly detail: string
  constructor(message: string, status: number, detail: string) {
    super(message)
    this.name = 'ChatAttachmentUploadError'
    this.status = status
    this.detail = detail
  }
}

/**
 * Upload one file and return chip-ready metadata. Throws
 * `ChatAttachmentUploadError` on non-2xx so the caller can surface a
 * typed error instead of swallowing it.
 *
 * `customerId` is forwarded as the multipart `customer_id` field. When
 * omitted, the backend uses the anon-tenant UUID — fine for dev /
 * single-tenant deployments; production multi-tenant should pass the
 * authenticated user's customer id.
 *
 * `fetch` is injectable for tests.
 */
export async function uploadChatAttachment(
  file: File,
  options: {
    baseUrl?: string
    customerId?: string
    bearerToken?: string
    fetch?: typeof globalThis.fetch
  } = {},
): Promise<ChatAttachment> {
  const fetchFn = options.fetch ?? globalThis.fetch.bind(globalThis)
  const baseUrl = options.baseUrl ?? ''
  const form = new FormData()
  form.append('file', file)
  if (options.customerId) form.append('customer_id', options.customerId)

  const headers: Record<string, string> = {}
  if (options.bearerToken) headers.Authorization = `Bearer ${options.bearerToken}`

  const url = (baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl) + '/api/v1/chat-files'
  const response = await fetchFn(url, {
    method: 'POST',
    body: form,
    headers,
  })
  if (!response.ok) {
    const detail = await safeReadText(response)
    throw new ChatAttachmentUploadError(
      `Chat file upload failed (status ${response.status}): ${detail}`,
      response.status,
      detail,
    )
  }
  const payload = (await response.json()) as UploadResponse
  if (typeof payload.id !== 'string' || payload.id === '') {
    throw new ChatAttachmentUploadError(
      'Chat file upload returned no id',
      response.status,
      JSON.stringify(payload),
    )
  }
  return {
    id: payload.id,
    filename: payload.filename ?? file.name,
    mime_type: payload.mime_type ?? file.type ?? undefined,
    size_bytes: payload.size_bytes ?? file.size,
  }
}

async function safeReadText(res: Response): Promise<string> {
  try {
    return await res.text()
  } catch {
    return '<no body>'
  }
}

/**
 * Reactive Vue composable wrapping `uploadChatAttachment` with
 * uploading + error state. Use one per chat input instance.
 */
export function useChatAttachments() {
  const attachments = ref<ChatAttachment[]>([])
  const uploading = ref(false)
  const uploadError = ref<string | null>(null)

  async function addFiles(files: FileList | File[] | null | undefined) {
    if (!files || files.length === 0) return
    uploading.value = true
    uploadError.value = null
    try {
      // Sequential uploads — bounded backend pressure + clean per-file
      // error attribution. Most users attach 1-3 files per turn.
      for (const file of Array.from(files)) {
        const chip = await uploadChatAttachment(file)
        attachments.value = [...attachments.value, chip]
      }
    } catch (err) {
      if (err instanceof ChatAttachmentUploadError) {
        uploadError.value = err.message
      } else {
        uploadError.value = `Upload failed: ${err instanceof Error ? err.message : String(err)}`
      }
    } finally {
      uploading.value = false
    }
  }

  function removeAttachment(id: string) {
    attachments.value = attachments.value.filter((a) => a.id !== id)
  }

  function clear() {
    attachments.value = []
    uploadError.value = null
  }

  function ids(): string[] {
    return attachments.value.map((a) => a.id)
  }

  return {
    attachments,
    uploading,
    uploadError,
    addFiles,
    removeAttachment,
    clear,
    ids,
  }
}
