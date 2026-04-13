import { http, HttpResponse } from 'msw';

const handlers = [
	http.get('*/api/v1/info', () => {
		return HttpResponse.json({
			title: 'Test Service',
			version: '0.1.0',
			description: 'A test service'
		});
	}),

	http.get('*/api/v1/health/live', () => {
		return HttpResponse.json({
			status: 'UP',
			details: 'Service is running'
		});
	}),

	http.get('*/api/v1/health/ready', () => {
		return HttpResponse.json({
			status: 'UP',
			components: {
				database: {
					status: 'UP',
					latency_ms: 1.5,
					details: null
				}
			},
			system_info: {
				python_version: '3.13.0',
				platform: 'linux'
			}
		});
	}),

	// --- feature mock handlers ---
];

export { handlers };
