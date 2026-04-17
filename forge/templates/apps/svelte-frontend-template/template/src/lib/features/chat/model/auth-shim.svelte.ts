/**
 * Soft dependency on `$lib/core/auth/auth.svelte` so the chat module compiles
 * even when the project was scaffolded with `include_auth=false` (post_generate.py
 * removes the auth directory in that case). Returns a no-op `getToken` when auth
 * isn't present — the agent service in dev/no-auth setups doesn't require a Bearer
 * header (Gatekeeper passes traffic through).
 */

interface AuthLike {
	getToken?: () => Promise<string | null>;
}

let resolved: AuthLike | null = null;
let attempted = false;

async function resolveAuth(): Promise<AuthLike> {
	if (resolved) return resolved;
	if (attempted) return { getToken: async () => null };
	attempted = true;
	try {
		const mod = (await import('$lib/core/auth/auth.svelte')) as unknown as {
			getAuth: () => AuthLike;
		};
		resolved = mod.getAuth();
		return resolved;
	} catch {
		resolved = { getToken: async () => null };
		return resolved;
	}
}

export async function getOptionalAuthToken(): Promise<string | null> {
	const auth = await resolveAuth();
	if (typeof auth.getToken !== 'function') return null;
	return auth.getToken();
}
