/**
 * Inactivity-based session timeout — Svelte 5 runed module.
 *
 * Mirrors the Vue ``useSessionTimeout`` composable byte-for-byte
 * semantically: the platform reference implementation (BFF +
 * session-timeout RFC at ``~/.claude/plans/analyze-the-following-issue-lovely-sonnet.md``).
 *
 * Three cross-cutting concerns the naïve implementation gets wrong,
 * all solved here with browser-native primitives:
 *
 * 1. Drift-immune countdown — Chrome throttles ``setInterval`` to 1Hz
 *    in hidden tabs and to ~1 wake/min under Throttled Wake-Ups. We
 *    store an absolute target (``idleExpiresAt``) and recompute
 *    remaining via ``Date.now()`` at read time.
 *
 * 2. Cross-tab dedup — `BroadcastChannel` elects a leader; only one
 *    tab POSTs per activity burst.
 *
 * 3. Visibility gating — Every extension gated on
 *    ``document.visibilityState === 'visible'``.
 *
 * The runed module silently no-ops when:
 *  - Bootstrap returns 401 (unauthenticated route)
 *  - Bootstrap returns timeouts of 0 (server-side disabled)
 *
 * Wire it once at the authenticated layout's mount; do not call it
 * per-route.
 */

/** Response shape from GET / POST /auth/session. */
export interface SessionState {
	idle_remaining_seconds: number;
	absolute_remaining_seconds: number;
	idle_timeout_seconds: number;
	absolute_timeout_seconds: number;
	warn_at_seconds: number;
}

export interface SessionTimeoutOptions {
	/** Override the bootstrap endpoint. Default `/auth/session`. */
	endpoint?: string;
	/** Override the BroadcastChannel name. Default `forge-session-activity`. */
	channelName?: string;
	/** Activity-debounce window in ms. Default 30_000 (matches platform RFC). */
	debounceMs?: number;
	/** Per-tick reactivity refresh in ms. Default 1_000. */
	tickMs?: number;
}

const _DEFAULT_ENDPOINT = '/auth/session';
const _DEFAULT_CHANNEL = 'forge-session-activity';
const _DEFAULT_DEBOUNCE_MS = 30_000;
const _DEFAULT_TICK_MS = 1_000;

const _ACTIVITY_EVENTS = ['mousemove', 'keydown', 'scroll', 'visibilitychange'] as const;

// Module-level reactive state — Svelte 5 runes.
let enabled = $state(false);
let idleExpiresAt = $state(0);
let absoluteExpiresAt = $state(0);
let warnAtSeconds = $state(60);
let tickHeartbeat = $state(0);

let tickInterval: ReturnType<typeof setInterval> | null = null;
let channel: BroadcastChannel | null = null;
let lastSeenActivity = 0;
let pendingDebounceTimer: ReturnType<typeof setTimeout> | null = null;
let isMounted = false;

let opts: Required<SessionTimeoutOptions> = {
	endpoint: _DEFAULT_ENDPOINT,
	channelName: _DEFAULT_CHANNEL,
	debounceMs: _DEFAULT_DEBOUNCE_MS,
	tickMs: _DEFAULT_TICK_MS
};

function applyState(state: SessionState): void {
	if (state.idle_timeout_seconds === 0 && state.absolute_timeout_seconds === 0) {
		// Server-side timeouts disabled — keep module inert.
		enabled = false;
		return;
	}
	enabled = true;
	idleExpiresAt = Date.now() + state.idle_remaining_seconds * 1000;
	absoluteExpiresAt = Date.now() + state.absolute_remaining_seconds * 1000;
	warnAtSeconds = state.warn_at_seconds;
}

async function bootstrap(): Promise<void> {
	try {
		const res = await fetch(opts.endpoint, { credentials: 'include' });
		if (!res.ok) {
			enabled = false;
			return;
		}
		const state = (await res.json()) as SessionState;
		applyState(state);
	} catch {
		enabled = false;
	}
}

async function extend(): Promise<void> {
	if (!enabled) {
		return;
	}
	try {
		const res = await fetch(opts.endpoint, { method: 'POST', credentials: 'include' });
		if (!res.ok) {
			if (res.status === 401) {
				// Session expired between extension trigger and POST — let the
				// API layer's 401 handler drive the redirect.
				enabled = false;
			}
			return;
		}
		const state = (await res.json()) as SessionState;
		applyState(state);
		channel?.postMessage({ type: 'extended', expiresAt: idleExpiresAt });
	} catch {
		// Network blip — silently ignore; next activity will retry.
	}
}

function onUserActive(): void {
	if (!isMounted) {
		return;
	}
	if (typeof document === 'undefined' || document.visibilityState !== 'visible') {
		return;
	}
	if (!enabled) {
		return;
	}
	if (pendingDebounceTimer !== null) {
		return; // Inside the debounce window already.
	}
	pendingDebounceTimer = setTimeout(async () => {
		pendingDebounceTimer = null;
		if (!isMounted || document.visibilityState !== 'visible' || !enabled) {
			return;
		}
		// Leader election.
		const myTimestamp = Date.now();
		channel?.postMessage({ type: 'activity-claim', timestamp: myTimestamp });
		// Yield one event-loop tick so sibling claims arrive.
		await new Promise<void>((resolve) => setTimeout(resolve, 50));
		if (lastSeenActivity > myTimestamp) {
			return; // A sibling won; their broadcast will sync our state.
		}
		await extend();
	}, opts.debounceMs);
}

function onChannelMessage(msg: MessageEvent): void {
	const data = msg.data as { type?: string; expiresAt?: number; timestamp?: number } | null;
	if (!data || typeof data !== 'object') {
		return;
	}
	if (data.type === 'extended' && typeof data.expiresAt === 'number') {
		idleExpiresAt = data.expiresAt;
		return;
	}
	if (data.type === 'activity-claim' && typeof data.timestamp === 'number') {
		if (data.timestamp > lastSeenActivity) {
			lastSeenActivity = data.timestamp;
		}
	}
}

function attachListeners(): void {
	if (typeof window === 'undefined') {
		return;
	}
	if (typeof BroadcastChannel !== 'undefined') {
		channel = new BroadcastChannel(opts.channelName);
		channel.onmessage = onChannelMessage;
	}
	for (const event of _ACTIVITY_EVENTS) {
		window.addEventListener(event, onUserActive, { passive: true });
	}
	tickInterval = setInterval(() => {
		tickHeartbeat++;
	}, opts.tickMs);
}

function detachListeners(): void {
	if (typeof window === 'undefined') {
		return;
	}
	for (const event of _ACTIVITY_EVENTS) {
		window.removeEventListener(event, onUserActive);
	}
	if (tickInterval !== null) {
		clearInterval(tickInterval);
		tickInterval = null;
	}
	if (pendingDebounceTimer !== null) {
		clearTimeout(pendingDebounceTimer);
		pendingDebounceTimer = null;
	}
	channel?.close();
	channel = null;
}

/**
 * Activity-driven session-timeout module API.
 *
 * Call ``init()`` once at the authenticated layout's mount and
 * ``destroy()`` once on unmount. The returned object exposes
 * runed getters for the countdown values + an ``extend()`` method
 * for the modal's "Stay signed in" action.
 */
export function getSessionTimeout(options: SessionTimeoutOptions = {}) {
	opts = {
		endpoint: options.endpoint ?? _DEFAULT_ENDPOINT,
		channelName: options.channelName ?? _DEFAULT_CHANNEL,
		debounceMs: options.debounceMs ?? _DEFAULT_DEBOUNCE_MS,
		tickMs: options.tickMs ?? _DEFAULT_TICK_MS
	};

	const idleRemaining = $derived(
		// Touching the heartbeat re-runs this derived every tick.
		// `Date.now()` is always correct — drift-immune.
		(() => {
			void tickHeartbeat;
			if (!enabled) return 0;
			return Math.max(0, Math.floor((idleExpiresAt - Date.now()) / 1000));
		})()
	);

	const absoluteRemaining = $derived(
		(() => {
			void tickHeartbeat;
			if (!enabled) return 0;
			return Math.max(0, Math.floor((absoluteExpiresAt - Date.now()) / 1000));
		})()
	);

	async function init() {
		if (isMounted) return;
		isMounted = true;
		await bootstrap();
		if (enabled) {
			attachListeners();
		}
	}

	function destroy() {
		isMounted = false;
		detachListeners();
	}

	async function reload() {
		await bootstrap();
	}

	return {
		get enabled() {
			return enabled;
		},
		get idleRemaining() {
			return idleRemaining;
		},
		get absoluteRemaining() {
			return absoluteRemaining;
		},
		get warnAtSeconds() {
			return warnAtSeconds;
		},
		extend,
		reload,
		init,
		destroy
	};
}
