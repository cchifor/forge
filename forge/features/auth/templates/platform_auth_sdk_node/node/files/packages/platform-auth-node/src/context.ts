/**
 * AsyncLocalStorage-backed identity context propagation.
 *
 * Mirrors Python `platform_auth.identity` ContextVar usage: lets
 * background tasks (queue consumers, scheduled jobs, fire-and-forget
 * promises spawned from a request handler) access the current
 * `IdentityContext` without threading it through every function
 * signature.
 *
 * Usage:
 *
 * ```ts
 * import { identityContext, runWithIdentity } from "@forge/platform-auth-node";
 *
 * // Inside a request handler, after AuthGuard verified:
 * await runWithIdentity(req.identity!, async () => {
 *   // Anywhere in this async sub-tree — even after `await`s — the
 *   // identity is recoverable.
 *   queueClient.enqueue(async () => {
 *     const identity = identityContext.get();
 *     // The task that picks this up later sees the SAME identity.
 *   });
 * });
 *
 * // Or in a worker / consumer that receives a serialized identity:
 * await runWithIdentity(deserialize(message.identity), async () => {
 *   await processMessage(message);
 * });
 * ```
 *
 * The Fastify plugin (`./plugin.ts`) automatically wraps the
 * downstream onRequest chain with `runWithIdentity` so handler
 * authors don't need to remember the wiring — `identityContext.get()`
 * just works.
 */

import { AsyncLocalStorage } from "node:async_hooks";

import type { IdentityContext } from "./IdentityContext.js";

/**
 * Module-level AsyncLocalStorage. One instance per process —
 * reusable across libraries that consume this SDK. Importing the
 * same `identityContext` from anywhere in the dep tree returns the
 * same store.
 */
export const identityContext = new AsyncLocalStorage<IdentityContext>();

/**
 * Run `fn` with `identity` bound as the current async-local value.
 *
 * Inside `fn` (and every `await` chain reachable from it),
 * `identityContext.getStore()` returns `identity`. Outside, it
 * returns `undefined`.
 *
 * Returns whatever `fn` returns. Doesn't catch errors — they
 * propagate, with the async-local context still unwinding correctly
 * (`AsyncLocalStorage.run` handles cleanup via Node's async hooks).
 */
export async function runWithIdentity<T>(
  identity: IdentityContext,
  fn: () => Promise<T>,
): Promise<T> {
  return identityContext.run(identity, fn);
}

/**
 * Get the current identity, or `undefined` if no `runWithIdentity`
 * scope is active. Most callers should require an identity (mis-wired
 * code that runs auth-required logic without auth context is a bug);
 * use `requireIdentity()` for the fail-fast variant.
 */
export function getCurrentIdentity(): IdentityContext | undefined {
  return identityContext.getStore();
}

/**
 * Get the current identity or throw `Error` if not in scope.
 *
 * Use from code paths that ASSUME they're running inside a
 * verified-request context (e.g., a service-layer function called
 * from a route handler). The throw surfaces mis-wiring as a
 * stack trace rather than silently producing a `tenant_id =
 * undefined` row.
 */
export function requireIdentity(): IdentityContext {
  const identity = identityContext.getStore();
  if (identity === undefined) {
    throw new Error(
      "platform-auth: requireIdentity() called outside of a runWithIdentity " +
        "scope. Wire AuthGuard or call runWithIdentity(identity, fn) before " +
        "running code that depends on the current caller.",
    );
  }
  return identity;
}
