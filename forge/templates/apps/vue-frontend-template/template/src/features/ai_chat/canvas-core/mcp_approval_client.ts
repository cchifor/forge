/**
 * MCP approval-aware invocation client.
 *
 * **This is a wire-protocol bug fix.** Before this file existed:
 *
 *   - The Python backend (`forge/features/platform/templates/mcp_server/python/files/src/app/mcp/router.py`
 *     lines 176–195) requires an HMAC-signed `approval_token` when a
 *     tool's `approval_mode != "auto"`. Missing or stale tokens →
 *     HTTP 401 with `"Approval token missing or invalid. Call
 *     /mcp/approval/mint first."`
 *   - The Svelte client (`use-mcp-tools.svelte.ts:65-72`) calls
 *     `/mcp/invoke` directly without ever minting a token.
 *   - The Dart client (`mcp_client.dart:72-76`) does the same.
 *   - Vue has no MCP client today.
 *
 * The net effect: every non-`auto` MCP tool invocation 401'd, silently
 * masked by the MCP UI panels being stubs that nobody routed real
 * traffic through. As soon as the Tool Library panel work in Pillar F
 * lights up real traffic, the bug would crash every invocation.
 *
 * This client:
 *
 *   1. Calls `POST /mcp/approval/mint` with `{server, tool, input}` to
 *      get a signed token.
 *   2. Calls `POST /mcp/invoke` with `{server, tool, input, approval_token}`.
 *   3. Caches the token per (server, tool, input_hash) for the
 *      session — the backend's hash matches the input verbatim, so a
 *      changed input forces a re-mint (correct: prevents replay).
 *   4. Refreshes on token expiry (TTL 3600s per `audit.py:130`).
 *   5. Surfaces 401 errors with a clear remediation message so
 *      operators don't have to grep the backend logs.
 *
 * The `auto` mode short-circuits straight to `/mcp/invoke` without a
 * mint call — the backend doesn't require a token in that mode.
 */

export type ApprovalMode = 'auto' | 'prompt-once' | 'prompt-every'

export interface McpInvokeRequest {
  server: string
  tool: string
  input: Record<string, unknown>
  /**
   * Per-tool approval mode. When `"auto"`, no mint call is made.
   * When `"prompt-once"` or `"prompt-every"`, the client mints a token
   * before invoking. The Tool Library / Approval Dialog (Pillar F.3 +
   * F.4) is responsible for actually prompting the user; this client
   * assumes the consent decision has already been made.
   */
  approvalMode: ApprovalMode
}

export interface McpInvokeResult {
  ok: boolean
  output?: unknown
  error?: string
}

export interface McpApprovalClientOptions {
  /**
   * Base URL for the MCP endpoints. Defaults to `""` (same origin) so
   * the typical Vite proxy + Caddy / Traefik setup works out of the
   * box. Use an absolute URL for cross-origin host configurations.
   */
  baseUrl?: string
  /**
   * Optional `fetch` override for testing or for callers that need to
   * inject custom headers (e.g. auth Bearer tokens). Defaults to the
   * global `fetch`.
   */
  fetch?: typeof globalThis.fetch
  /**
   * Token TTL in milliseconds. Defaults to 1 hour to match the Python
   * backend's `MCP_APPROVAL_TOKEN_TTL_SECONDS` of 3600 (see
   * `audit.py:130`). Lower this if the backend shortens TTL; raising
   * it past the server-side TTL would just produce expected 401s on
   * stale tokens.
   */
  tokenTtlMs?: number
  /**
   * Optional clock for testing — defaults to `Date.now`. Reading from
   * the option lets the cache eviction be deterministic in tests
   * without freezing global time.
   */
  now?: () => number
}

interface CachedToken {
  token: string
  /** Wall-clock ms when this token expires (issuedAt + ttlMs). */
  expiresAt: number
}

/**
 * Default TTL matches the backend's MCP_APPROVAL_TOKEN_TTL_SECONDS.
 * Trimmed by 30s to avoid race conditions on tokens about to expire
 * (the backend's clock and the client's drift).
 */
const DEFAULT_TOKEN_TTL_MS = (3600 - 30) * 1000

/**
 * One-shot error thrown when invoke returns 401 even after minting.
 * Surfaced separately so UI layers can show "the backend rejected the
 * approval token — re-approve" rather than a generic network error.
 */
export class McpApprovalRejected extends Error {
  readonly status: number
  readonly server: string
  readonly tool: string
  readonly detail: string

  constructor(args: {
    server: string
    tool: string
    status: number
    detail: string
  }) {
    super(
      `MCP invocation of ${args.server}:${args.tool} rejected with status ${args.status}: ${args.detail}`,
    )
    this.name = 'McpApprovalRejected'
    this.status = args.status
    this.server = args.server
    this.tool = args.tool
    this.detail = args.detail
  }
}

export class McpApprovalClient {
  private readonly baseUrl: string
  private readonly fetchFn: typeof globalThis.fetch
  private readonly tokenTtlMs: number
  private readonly now: () => number
  private readonly tokenCache = new Map<string, CachedToken>()

  constructor(options: McpApprovalClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? ''
    this.fetchFn = options.fetch ?? globalThis.fetch.bind(globalThis)
    this.tokenTtlMs = options.tokenTtlMs ?? DEFAULT_TOKEN_TTL_MS
    this.now = options.now ?? Date.now
  }

  /**
   * Invoke an MCP tool, minting an approval token first when required.
   *
   * Throws `McpApprovalRejected` on 401 (after mint), wraps other
   * non-2xx responses in a generic `Error` with the status + body.
   */
  async invoke(req: McpInvokeRequest): Promise<McpInvokeResult> {
    let approvalToken: string | undefined
    if (req.approvalMode !== 'auto') {
      approvalToken = await this.ensureToken(req)
    }
    return this.invokeWithToken(req, approvalToken)
  }

  /**
   * Force-evict any cached token for this tuple. Useful when the caller
   * knows the input is about to change (e.g. user edited a parameter
   * in the approval dialog) so the next invoke re-mints with the new
   * input rather than failing the server-side hash check.
   */
  evict(req: Pick<McpInvokeRequest, 'server' | 'tool' | 'input'>): void {
    this.tokenCache.delete(cacheKey(req))
  }

  /**
   * Reset all cached tokens. Call on logout, environment switch, or
   * when the user explicitly chooses "Never remember approvals".
   */
  clearCache(): void {
    this.tokenCache.clear()
  }

  private async ensureToken(req: McpInvokeRequest): Promise<string> {
    const key = cacheKey(req)
    const cached = this.tokenCache.get(key)
    if (cached && cached.expiresAt > this.now()) {
      return cached.token
    }
    const token = await this.mintToken(req)
    this.tokenCache.set(key, {
      token,
      expiresAt: this.now() + this.tokenTtlMs,
    })
    return token
  }

  private async mintToken(req: McpInvokeRequest): Promise<string> {
    const res = await this.fetchFn(this.url('/mcp/approval/mint'), {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ server: req.server, tool: req.tool, input: req.input }),
    })
    if (!res.ok) {
      const body = await safeReadText(res)
      throw new Error(
        `Failed to mint MCP approval token for ${req.server}:${req.tool} ` +
          `(status ${res.status}): ${body}`,
      )
    }
    const data = (await res.json()) as { token?: unknown }
    if (typeof data.token !== 'string' || data.token === '') {
      throw new Error(
        `MCP approval mint returned no token for ${req.server}:${req.tool}`,
      )
    }
    return data.token
  }

  private async invokeWithToken(
    req: McpInvokeRequest,
    approvalToken: string | undefined,
  ): Promise<McpInvokeResult> {
    const body: Record<string, unknown> = {
      server: req.server,
      tool: req.tool,
      input: req.input,
    }
    if (approvalToken !== undefined) {
      body['approval_token'] = approvalToken
    }
    const res = await this.fetchFn(this.url('/mcp/invoke'), {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (res.status === 401) {
      // Token was missing/invalid even though we (supposedly) minted
      // one — evict and surface so the UI can prompt for re-approval.
      this.evict(req)
      const detail = await safeReadText(res)
      throw new McpApprovalRejected({
        server: req.server,
        tool: req.tool,
        status: 401,
        detail,
      })
    }
    if (!res.ok) {
      const body = await safeReadText(res)
      throw new Error(
        `MCP invoke of ${req.server}:${req.tool} failed (status ${res.status}): ${body}`,
      )
    }
    return (await res.json()) as McpInvokeResult
  }

  private url(path: string): string {
    if (!this.baseUrl) return path
    // baseUrl may or may not have a trailing slash; normalize.
    const trimmed = this.baseUrl.endsWith('/')
      ? this.baseUrl.slice(0, -1)
      : this.baseUrl
    return trimmed + path
  }
}

function cacheKey(req: Pick<McpInvokeRequest, 'server' | 'tool' | 'input'>): string {
  // Key on (server, tool, stable-json-of-input). The backend's
  // signature is bound to a hash of the input, so a changed input
  // would invalidate the token anyway — keying on input keeps the
  // cache honest. `JSON.stringify` is order-sensitive; that's OK
  // because the same call site reliably builds the same shape.
  return `${req.server}::${req.tool}::${JSON.stringify(req.input)}`
}

async function safeReadText(res: Response): Promise<string> {
  try {
    return await res.text()
  } catch {
    return '<no body>'
  }
}
