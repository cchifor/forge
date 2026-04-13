import type { Router } from 'vue-router'
import { useAuth } from '@/shared/composables/useAuth'
import { watch } from 'vue'

export function setupRouterGuards(router: Router) {
  router.beforeEach(async (to) => {
    const { isAuthenticated, isLoading } = useAuth()

    // Wait for auth initialization to complete
    if (isLoading.value) {
      await new Promise<void>((resolve) => {
        const stop = watch(isLoading, (loading) => {
          if (!loading) {
            stop()
            resolve()
          }
        })
      })
    }

    const requiresAuth = to.matched.some(
      (record) => record.meta.requiresAuth !== false,
    )

    if (requiresAuth && !isAuthenticated.value) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }

    if (to.name === 'login' && isAuthenticated.value) {
      return { name: 'home' }
    }
  })
}
