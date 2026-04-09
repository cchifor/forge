import { ref, computed, readonly } from 'vue'

export interface AuthUser {
  id: string
  email: string
  username: string
  firstName: string
  lastName: string
  roles: string[]
  customerId: string
  orgId: string | null
}

const user = ref<AuthUser | null>(null)
const isLoading = ref(true)
const isInitialized = ref(false)

let authDisabled = false

const DEV_USER: AuthUser = {
  id: '00000000-0000-0000-0000-000000000001',
  email: 'dev@localhost',
  username: 'dev-user',
  firstName: 'Dev',
  lastName: 'User',
  roles: ['admin', 'user'],
  customerId: '00000000-0000-0000-0000-000000000001',
  orgId: null,
}

/**
 * Gatekeeper-based authentication composable.
 *
 * With Gatekeeper ForwardAuth, authentication is handled at the gateway level:
 * - If the user reaches the app, they are authenticated (Traefik/Gatekeeper
 *   would have redirected to Keycloak login otherwise).
 * - Login: redirect to /callback which triggers the OIDC authorization flow.
 * - Logout: redirect to /logout which clears the session cookie.
 * - User info: Gatekeeper injects X-Gatekeeper-* headers on proxied requests;
 *   the frontend fetches user info from the first backend's /api/whoami endpoint.
 * - Tokens are in HttpOnly cookies — no JS access needed.
 */
export function useAuth() {
  const isAuthenticated = computed(() => !!user.value)

  async function init() {
    if (isInitialized.value) return

    authDisabled = import.meta.env.VITE_AUTH_DISABLED === 'true'

    if (authDisabled) {
      user.value = DEV_USER
      isLoading.value = false
      isInitialized.value = true
      return
    }

    // With Gatekeeper ForwardAuth, if we can load the page we're authenticated.
    // Fetch user info from the gateway's /auth/userinfo endpoint.
    try {
      const res = await fetch('/auth/userinfo', { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        user.value = {
          id: data.userId || data.sub || '',
          email: data.email || '',
          username: data.preferredUsername || data.email || '',
          firstName: data.givenName || '',
          lastName: data.familyName || '',
          roles: data.roles || [],
          customerId: data.customerId || data.userId || data.sub || '',
          orgId: data.orgId || null,
        }
      } else {
        // Not authenticated — Gatekeeper will handle redirect on next navigation
        user.value = null
      }
    } catch {
      // Network error or CORS — treat as authenticated without user details
      // (Gatekeeper would have redirected if truly unauthenticated)
      user.value = null
    } finally {
      isLoading.value = false
      isInitialized.value = true
    }
  }

  async function getToken(): Promise<string | null> {
    if (authDisabled) return 'dev-token'
    // With Gatekeeper, the session token is in an HttpOnly cookie.
    // No client-side token access is needed — the cookie is sent automatically.
    return null
  }

  function login(redirectUri?: string) {
    if (authDisabled) {
      user.value = DEV_USER
      return
    }
    // Redirect to Gatekeeper's login endpoint to start the OIDC flow
    const redirect = redirectUri ?? window.location.href
    window.location.href = `/auth/login?redirect_uri=${encodeURIComponent(redirect)}`
  }

  function logout() {
    if (authDisabled) {
      user.value = null
      return
    }
    user.value = null
    window.location.href = '/logout'
  }

  function hasRole(role: string): boolean {
    return user.value?.roles.includes(role) ?? false
  }

  return {
    user: readonly(user),
    isAuthenticated,
    isLoading: readonly(isLoading),
    init,
    getToken,
    login,
    logout,
    hasRole,
  }
}
