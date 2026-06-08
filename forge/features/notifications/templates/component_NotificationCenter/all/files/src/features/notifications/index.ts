/**
 * Public exports for the notifications feature module.
 *
 * Components mount in the layout shell; ``startNotifications`` initialises the
 * SSE stream once after auth bootstrap. See the feature README for the one-time
 * wiring (bell into the header, ToastHost into the app root, the bootstrap call).
 */
export { default as NotificationBell } from './components/NotificationBell.vue'
export { default as NotificationCenter } from './components/NotificationCenter.vue'
export { default as NotificationConnectionBanner } from './components/NotificationConnectionBanner.vue'
export { default as ToastHost } from './components/ToastHost.vue'

export { startNotifications } from './composables/useNotifications'
export { useNotificationStore } from './store'
export { toast } from './toast'
export { registerInvalidation } from './invalidation'
export type { Notification, Severity, UnreadCount } from './types'
