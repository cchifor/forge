# Notification center

A live, SSE-driven notification stack: a header **bell** with an unread badge, a
**center** popover panel, a **toast** surface, and a Pinia **store** that is the
single source of truth. It consumes the app's event stream via the generic
`useEventStream` composable and reuses the project's TanStack Query + auth.

## What ships

- `features/notifications/` — `store.ts` (Pinia), `api/stream.ts` (SSE consumer,
  CloudEvent → notification adapter), `api/client.ts` (inbox REST), `toast.ts`,
  `invalidation.ts` (cache-invalidation registry), `navigate.ts`, and the
  `NotificationBell` / `NotificationCenter` / `NotificationConnectionBanner` /
  `ToastHost` components.
- `shared/ui/popover/` — a small Radix-Vue `Popover` (the bell uses it).
- `shared/components/RelativeTime.vue` + `shared/lib/formatTime.ts` — relative
  timestamps in the panel.

## Wiring (four one-time edits)

`.vue` files can't be auto-injected, so wire these by hand:

1. **Bell** — in `shared/components/AppHeader.vue`, in the right-aligned action
   group: `import { NotificationBell } from '@/features/notifications'` and add
   `<NotificationBell />`.
2. **Toast host + banner** — in `app/App.vue` (or your root layout):
   `import { ToastHost, NotificationConnectionBanner } from '@/features/notifications'`
   and render `<ToastHost />` + `<NotificationConnectionBanner />`. If you adopt
   `ToastHost` as the toast surface, remove the `vue-sonner` `<Toaster />` so you
   don't get two toast surfaces.
3. **Bootstrap** — in `app/main.ts`, after `router.isReady()` + auth:
   `import { startNotifications } from '@/features/notifications'` then
   `await startNotifications(queryClient)`.
4. **Cache invalidation** (optional) — register the entity types your backend
   emits so their notifications refresh the right queries:
   ```ts
   import { registerInvalidation } from '@/features/notifications'
   registerInvalidation('items', (id) => [
     ['items', 'list'],
     ...(id ? [['items', 'detail', id]] : []),
   ])
   ```

## Backend

The bell is driven by SSE from the generated `streaming` feature
(`GET /api/v1/stream`, CloudEvents). The inbox REST endpoints
(`api/v1/notifications…`) are optional — the store tolerates their absence (the
bell hydrates from the live stream). Implement them, or a CloudEvent → rendered
`Notification` renderer, to light up the persisted inbox + mark-read.
