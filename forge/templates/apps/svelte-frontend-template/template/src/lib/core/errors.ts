export function categorizeError(
	status: number
): 'not-found' | 'forbidden' | 'server' | 'unknown' {
	if (status === 404) return 'not-found';
	if (status === 403) return 'forbidden';
	if (status >= 500) return 'server';
	return 'unknown';
}

export function userFacingMessage(status: number, fallback?: string): string {
	switch (categorizeError(status)) {
		case 'not-found':
			return 'The page or resource you requested could not be found.';
		case 'forbidden':
			return 'You do not have permission to access this resource.';
		case 'server':
			return 'Something went wrong on our end. Please try again later.';
		default:
			return fallback ?? 'An unexpected error occurred.';
	}
}
