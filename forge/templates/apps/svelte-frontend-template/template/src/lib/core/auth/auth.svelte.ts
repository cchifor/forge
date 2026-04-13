export interface AuthUser {
	id: string;
	email: string;
	username: string;
	firstName: string;
	lastName: string;
	roles: string[];
	customerId: string;
	orgId: string | null;
}

const DEV_USER: AuthUser = {
	id: '00000000-0000-0000-0000-000000000001',
	email: 'dev@localhost',
	username: 'dev-user',
	firstName: 'Dev',
	lastName: 'User',
	roles: ['admin', 'user'],
	customerId: '00000000-0000-0000-0000-000000000001',
	orgId: null
};

// Module-level reactive state
let user = $state<AuthUser | null>(null);
let isLoading = $state(true);
let isInitialized = $state(false);

let authDisabled = false;

/**
 * Gatekeeper-based authentication composable.
 *
 * With Gatekeeper ForwardAuth, authentication is handled at the gateway level:
 * - If the user reaches the app, they are authenticated.
 * - Login: redirect to /auth/login which triggers the OIDC authorization flow.
 * - Logout: redirect to /logout which clears the session cookie.
 * - User info: fetched from /auth/userinfo (Gatekeeper decodes the JWT cookie).
 * - Tokens are in HttpOnly cookies — no JS access needed.
 */
export function getAuth() {
	const isAuthenticated = $derived(!!user);

	async function init() {
		if (isInitialized) return;

		authDisabled = import.meta.env.VITE_AUTH_DISABLED === 'true';

		if (authDisabled) {
			user = DEV_USER;
			isLoading = false;
			isInitialized = true;
			return;
		}

		// With Gatekeeper ForwardAuth, if we can load the page we're authenticated.
		// Fetch user info from the gateway's /auth/userinfo endpoint.
		try {
			const res = await fetch('/auth/userinfo', { credentials: 'include' });
			if (res.ok) {
				const data = await res.json();
				user = {
					id: data.userId || data.sub || '',
					email: data.email || '',
					username: data.preferredUsername || data.email || '',
					firstName: data.givenName || '',
					lastName: data.familyName || '',
					roles: data.roles || [],
					customerId: data.customerId || data.userId || data.sub || '',
					orgId: data.orgId || null
				};
			} else {
				user = null;
			}
		} catch {
			user = null;
		} finally {
			isLoading = false;
			isInitialized = true;
		}
	}

	async function getToken(): Promise<string | null> {
		if (authDisabled) return 'dev-token';
		// With Gatekeeper, the session token is in an HttpOnly cookie.
		// No client-side token access is needed — the cookie is sent automatically.
		return null;
	}

	function login(redirectUri?: string) {
		if (authDisabled) {
			user = DEV_USER;
			return;
		}
		// Redirect to Gatekeeper's login endpoint to start the OIDC flow
		const redirect = redirectUri ?? window.location.href;
		window.location.href = `/auth/login?redirect_uri=${encodeURIComponent(redirect)}`;
	}

	function logout() {
		if (authDisabled) {
			user = null;
			return;
		}
		user = null;
		window.location.href = '/logout';
	}

	function hasRole(role: string): boolean {
		return user?.roles.includes(role) ?? false;
	}

	return {
		get user() {
			return user;
		},
		get isAuthenticated() {
			return isAuthenticated;
		},
		get isLoading() {
			return isLoading;
		},
		init,
		getToken,
		login,
		logout,
		hasRole
	};
}
