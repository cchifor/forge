<script lang="ts">
	/**
	 * Pre-warning session-timeout modal — Svelte 5 runed component.
	 *
	 * Mirrors the Vue ``SessionTimeoutModal.vue`` behaviour:
	 * opens at ``T - warnAtSeconds`` from idle expiry, displays a live
	 * countdown, and offers two actions:
	 *  - "Stay signed in" → fires an immediate extension via
	 *    ``getSessionTimeout().extend()``, bypassing the activity debounce.
	 *  - "Sign out" → existing /logout flow (browser navigation).
	 *
	 * Visibility-gated: backgrounded tabs don't spam hidden countdowns.
	 *
	 * Wire once at the authenticated layout's root; the runed module
	 * is the single source of "user is here" — calling a backend
	 * endpoint does NOT reset the timer (per platform's BFF +
	 * session-timeout RFC).
	 */
	import { getSessionTimeout } from '../../../core/auth/session-timeout.svelte';

	interface Props {
		/** Override the logout URL. Default `/logout`. */
		logoutUrl?: string;
	}

	let { logoutUrl = '/logout' }: Props = $props();

	const session = getSessionTimeout();
	let isExtending = $state(false);
	let visibilityState = $state<DocumentVisibilityState>('visible');

	function syncVisibility() {
		if (typeof document !== 'undefined') {
			visibilityState = document.visibilityState;
		}
	}

	$effect(() => {
		syncVisibility();
		if (typeof document === 'undefined') return;
		document.addEventListener('visibilitychange', syncVisibility);
		return () => {
			document.removeEventListener('visibilitychange', syncVisibility);
		};
	});

	const isVisible = $derived(
		session.enabled &&
			session.idleRemaining > 0 &&
			session.idleRemaining <= session.warnAtSeconds &&
			visibilityState === 'visible'
	);

	const formatted = $derived(
		(() => {
			const remaining = session.idleRemaining;
			const m = Math.floor(remaining / 60);
			const s = remaining % 60;
			return m > 0 ? `${m}m ${s}s` : `${s}s`;
		})()
	);

	async function staySignedIn() {
		if (isExtending) return;
		isExtending = true;
		try {
			await session.extend();
		} finally {
			isExtending = false;
		}
	}

	function signOut() {
		window.location.href = logoutUrl;
	}
</script>

{#if isVisible}
	<div
		class="session-timeout-modal-backdrop"
		role="dialog"
		aria-modal="true"
		aria-labelledby="session-timeout-title"
	>
		<div class="session-timeout-modal">
			<h2 id="session-timeout-title">You'll be signed out soon</h2>
			<p>
				For your security, you'll be signed out in
				<strong>{formatted}</strong>
				unless you stay active.
			</p>
			<div class="session-timeout-actions">
				<button
					type="button"
					class="session-timeout-primary"
					disabled={isExtending}
					onclick={staySignedIn}
				>
					{isExtending ? 'Staying signed in…' : 'Stay signed in'}
				</button>
				<button type="button" class="session-timeout-secondary" onclick={signOut}>
					Sign out
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.session-timeout-modal-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.45);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 9999;
	}

	.session-timeout-modal {
		background: var(--color-surface, #ffffff);
		color: var(--color-text, #111827);
		border-radius: 0.5rem;
		padding: 1.5rem;
		max-width: 420px;
		width: 90%;
		box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
	}

	.session-timeout-modal h2 {
		margin: 0 0 0.75rem;
		font-size: 1.25rem;
	}

	.session-timeout-modal p {
		margin: 0 0 1.25rem;
		line-height: 1.5;
	}

	.session-timeout-actions {
		display: flex;
		gap: 0.75rem;
		justify-content: flex-end;
	}

	.session-timeout-primary,
	.session-timeout-secondary {
		border-radius: 0.375rem;
		padding: 0.5rem 1rem;
		font-size: 0.95rem;
		cursor: pointer;
		border: 1px solid transparent;
	}

	.session-timeout-primary {
		background: var(--color-primary, #2563eb);
		color: #ffffff;
	}

	.session-timeout-primary:disabled {
		opacity: 0.6;
		cursor: progress;
	}

	.session-timeout-secondary {
		background: transparent;
		color: var(--color-text, #111827);
		border-color: var(--color-border, #d1d5db);
	}
</style>
