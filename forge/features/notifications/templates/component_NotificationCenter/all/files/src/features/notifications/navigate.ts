/**
 * Notification deep-link navigation guard.
 *
 * A notification's ``deep_link`` may drift from the SPA route table, or the
 * linked entity may have been deleted since the notification was rendered — a
 * naive ``router.push(deepLink)`` would then land the user on the catch-all
 * ``not-found`` route, which feels like a broken bell. This helper resolves the
 * link first; on a not-found match the caller surfaces a small toast instead of
 * navigating. Pure function so it can be unit-tested without mounting the panel.
 */
import type { Router, RouteLocationNormalizedLoaded } from 'vue-router'

const NOT_FOUND_ROUTE_NAME = 'not-found'

export interface NavigateOutcome {
  /** ``'navigate'`` when the link resolved to a real route and was pushed; */
  /** ``'unavailable'`` when the link resolved to the catch-all not-found. */
  result: 'navigate' | 'unavailable'
  resolved?: RouteLocationNormalizedLoaded
}

export function navigateToDeepLink(
  router: Pick<Router, 'resolve' | 'push'>,
  deepLink: string,
): NavigateOutcome {
  const resolved = router.resolve(deepLink)
  if (resolved.matched.length === 0 || resolved.name === NOT_FOUND_ROUTE_NAME) {
    return { result: 'unavailable' }
  }
  void router.push(resolved as RouteLocationNormalizedLoaded).catch(() => undefined)
  return { result: 'navigate', resolved: resolved as RouteLocationNormalizedLoaded }
}
