export async function enableMockingIfNeeded(): Promise<void> {
	if (import.meta.env.DEV && import.meta.env.VITE_ENABLE_MOCKS === 'true') {
		const { worker } = await import('../../test/mocks/browser');
		await worker.start({
			onUnhandledRequest: 'bypass',
			serviceWorker: { url: '/mockServiceWorker.js' }
		});
		console.log('[MSW] Mock service worker started');
	}
}
