/**
 * Synchronous one-shot toast helper backed by the notification store.
 *
 * The store's primary lifecycle is **optimistic + SSE merge** for async actions.
 * This shim covers the simpler case: synchronous work whose success/failure is
 * known immediately, where there's no server event to wait for.
 *
 * The API surface mirrors vue-sonner's common usage (``toast.success``,
 * ``toast.error``, ``toast.info``, ``toast.warning``, ``toast.loading``,
 * ``toast.message``, ``toast.promise``) so callers only swap the import path.
 * Each call generates a unique correlation key — these toasts are one-shots;
 * they never dedupe against optimistic SSE-paired toasts.
 */
import { useNotificationStore } from './store'

let counter = 0
function newId(): string {
  counter += 1
  return `oneshot-${Date.now()}-${counter}`
}

export interface ToastOptions {
  /** Stable id so the same toast can be updated in place (e.g.
   *  ``toast.loading(...)`` then ``toast.success('done', {id})``). */
  id?: string
  description?: string
}

type SyncSeverity = 'success' | 'error' | 'info' | 'warn'

function pushOneShot(
  state: SyncSeverity | 'pending',
  title: string,
  opts: ToastOptions,
): string {
  const store = useNotificationStore()
  const id = opts.id ?? newId()
  const correlationKey = `oneshot:${id}:default`

  // Update-in-place when an id is reused — vue-sonner semantics.
  const existing = store.toasts.find((t) => t.correlationKey === correlationKey)
  if (existing) {
    if (state === 'pending') {
      // Idempotent: a second ``loading`` with the same id is a no-op.
      return id
    }
    store.resolveToast(correlationKey, {
      state,
      severity: state === 'warn' ? 'warn' : state,
      title,
      body: opts.description ?? null,
      deep_link: null,
    })
    return id
  }

  store.pushOptimistic({
    entityType: 'oneshot',
    entityId: id,
    verb: 'default',
    title,
    body: opts.description ?? null,
  })
  if (state !== 'pending') {
    store.resolveToast(correlationKey, {
      state,
      severity: state === 'warn' ? 'warn' : state,
      title,
      body: opts.description ?? null,
      deep_link: null,
    })
  }
  return id
}

export interface ToastPromiseOptions<T> {
  loading: string
  success: string | ((value: T) => string | { message: string; type: 'error' })
  error: string | ((err: Error) => string)
}

/**
 * Resolve ``promise`` while showing a loading toast that flips to a success or
 * error toast when the promise settles. Mirrors ``vue-sonner``'s
 * ``toast.promise`` shape.
 */
async function toastPromise<T>(
  promise: Promise<T>,
  opts: ToastPromiseOptions<T>,
): Promise<T> {
  const id = pushOneShot('pending', opts.loading, {})
  try {
    const value = await promise
    const resolved = typeof opts.success === 'function' ? opts.success(value) : opts.success
    if (typeof resolved === 'object' && resolved.type === 'error') {
      pushOneShot('error', resolved.message, { id })
    } else {
      const title = typeof resolved === 'string' ? resolved : resolved.message
      pushOneShot('success', title, { id })
    }
    return value
  } catch (err) {
    const msg =
      typeof opts.error === 'function'
        ? opts.error(err instanceof Error ? err : new Error(String(err)))
        : opts.error
    pushOneShot('error', msg, { id })
    throw err
  }
}

export const toast = {
  success: (title: string, opts: ToastOptions = {}) =>
    pushOneShot('success', title, opts),
  error: (title: string, opts: ToastOptions = {}) =>
    pushOneShot('error', title, opts),
  info: (title: string, opts: ToastOptions = {}) => pushOneShot('info', title, opts),
  /** Neutral/informational toast (vue-sonner alias for an untyped message). */
  message: (title: string, opts: ToastOptions = {}) => pushOneShot('info', title, opts),
  warning: (title: string, opts: ToastOptions = {}) =>
    pushOneShot('warn', title, opts),
  loading: (title: string, opts: ToastOptions = {}) =>
    pushOneShot('pending', title, opts),
  promise: toastPromise,
}
