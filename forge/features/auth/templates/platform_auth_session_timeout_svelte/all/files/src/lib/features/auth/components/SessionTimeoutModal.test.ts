import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { getSessionTimeout } from '../../../core/auth/session-timeout.svelte';
import SessionTimeoutModal from './SessionTimeoutModal.svelte';

const SESSION = {
	idle_remaining_seconds: 90,
	absolute_remaining_seconds: 3600,
	idle_timeout_seconds: 900,
	absolute_timeout_seconds: 28800,
	warn_at_seconds: 120
};

let visibility: 'visible' | 'hidden';
let destroy: () => void;

function respond(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'Content-Type': 'application/json' }
	});
}

/** Bootstrap the session module, then mount the modal on it. */
async function mountModal(props: { logoutUrl?: string } = {}) {
	const session = getSessionTimeout();
	destroy = session.destroy;
	await session.init();
	render(SessionTimeoutModal, { props });
	await tick();
}

function navigation() {
	const href = vi.fn();
	vi.spyOn(window, 'location', 'get').mockReturnValue(
		new Proxy(window.location, {
			set(_target, prop, value) {
				if (prop === 'href') href(value);
				return true;
			}
		})
	);
	return href;
}

beforeEach(() => {
	vi.useFakeTimers();
	vi.stubGlobal('BroadcastChannel', undefined);
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(SESSION)));
	visibility = 'visible';
	vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility);
	destroy = () => {};
});

afterEach(() => {
	cleanup();
	destroy();
	vi.useRealTimers();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

it('warns inside the threshold with a live countdown', async () => {
	await mountModal();
	expect(screen.getByRole('dialog').getAttribute('aria-labelledby')).toBe('session-timeout-title');
	expect(screen.getByRole('dialog').textContent).toContain('1m 30s');

	await vi.advanceTimersByTimeAsync(45_000);
	await tick();
	expect(screen.getByRole('dialog').textContent).toContain('45s');
});

it('stays closed outside the threshold', async () => {
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond({ ...SESSION, idle_remaining_seconds: 300 })));
	await mountModal();
	expect(screen.queryByRole('dialog')).toBeNull();
});

it('stays closed when the countdown is off', async () => {
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond({}, 401)));
	await mountModal();
	expect(screen.queryByRole('dialog')).toBeNull();
});

it('closes once the session has expired', async () => {
	await mountModal();
	await vi.advanceTimersByTimeAsync(91_000);
	await tick();
	expect(screen.queryByRole('dialog')).toBeNull();
});

it('closes in a hidden tab', async () => {
	await mountModal();
	visibility = 'hidden';
	document.dispatchEvent(new Event('visibilitychange'));
	await tick();
	expect(screen.queryByRole('dialog')).toBeNull();
});

it('extends the session once while a request is in flight', async () => {
	await mountModal();
	let finish!: (response: Response) => void;
	const fetchMock = vi.mocked(fetch);
	fetchMock.mockReturnValueOnce(new Promise<Response>((resolve) => (finish = resolve)));
	const stay = screen.getByRole('button', { name: 'Stay signed in' });

	stay.click();
	stay.click();
	await tick();
	expect(fetchMock).toHaveBeenCalledTimes(2);
	expect(fetchMock).toHaveBeenLastCalledWith('/auth/session', { method: 'POST', credentials: 'include' });
	expect(stay.textContent?.trim()).toBe('Staying signed in…');
	expect((stay as HTMLButtonElement).disabled).toBe(true);

	finish(respond({ ...SESSION, idle_remaining_seconds: 900 }));
	await vi.advanceTimersByTimeAsync(0);
	await tick();
	expect(screen.queryByRole('dialog')).toBeNull();
});

it.each([
	[undefined, '/logout'],
	['/auth/logout', '/auth/logout']
])('signs out through %s', async (logoutUrl, expected) => {
	const href = navigation();
	await mountModal(logoutUrl ? { logoutUrl } : {});
	await fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
	expect(href).toHaveBeenCalledWith(expected);
});
