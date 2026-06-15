/**
 * @forge/platform-auth-node
 *
 * Identity, RBAC, and S2S authentication primitives for Fastify
 * services. Node port of platform-auth (Python). Public surface is
 * intentionally small — anything not listed in the named exports
 * below is an implementation detail and may change without warning.
 *
 * Cross-language parity with the Python SDK is enforced by the
 * cross-SDK parity test suite at
 * forge/tests/contract/auth_sdk_parity/ — same JWT inputs must yield
 * matching IdentityContext outputs (or matching exceptions) across
 * Python, Node, and Rust.
 */

export {
  AuthGuard,
  DEFAULT_ALGORITHMS,
  DEFAULT_CLOCK_SKEW_SECONDS,
  DEFAULT_ROLES_CLAIM,
  DEFAULT_SCOPE_CLAIM,
  DEFAULT_TENANT_ID_CLAIM,
  DEFAULT_TENANT_SLUG_CLAIM,
  REQUIRED_CLAIMS,
  requireScope,
  type AuthAuditCallback,
  type AuthAuditRecord,
  type AuthGuardConfig,
  type RequestLike,
} from "./AuthGuard.js";

export {
  ActorNotAuthorized,
  AuthError,
  InvalidToken,
  IssuerNotTrusted,
  S2SAuthError,
  ScopeRequired,
  TenantSuspended,
  TokenExpired,
  TokenRevoked,
} from "./exceptions.js";

export {
  buildIdentity,
  PLATFORM_SUPPORT_READ,
  PLATFORM_SUPPORT_WRITE,
  type IdentityContext,
} from "./IdentityContext.js";

export {
  DEFAULT_HTTP_TIMEOUT_MS,
  DEFAULT_LIFESPAN_SECONDS,
  DEFAULT_STALE_MAX_SECONDS,
  JWKSCache,
  type JWKSCacheOptions,
} from "./JWKSCache.js";

export {
  AllowAllMayActPolicy,
  StaticMayActPolicy,
  type MayActPolicy,
} from "./may_act.js";

export {
  InMemoryRevocationStore,
  NeverRevokedStore,
  type RevocationStore,
} from "./revocation.js";

export {
  getCurrentIdentity,
  identityContext,
  requireIdentity,
  runWithIdentity,
} from "./context.js";

export {
  createAuthMiddleware,
  type AuthMiddlewareResult,
  type MinimalRequest,
  type RunAuthMiddlewareOptions,
} from "./middleware.js";

export {
  DEFAULT_EXCLUDED_PATHS,
  platformAuthPlugin,
  type PlatformAuthPluginOptions,
} from "./plugin.js";

export {
  DEFAULT_HTTP_TIMEOUT_MS as DEFAULT_S2S_HTTP_TIMEOUT_MS,
  DEFAULT_MAX_CACHE_ENTRIES as DEFAULT_S2S_MAX_CACHE_ENTRIES,
  DEFAULT_SAFETY_MARGIN_SECONDS,
  S2SClient,
  type CacheStats,
  type RequestOptions as S2SRequestOptions,
  type S2SClientOptions,
} from "./S2SClient.js";

export { ROOT_WILDCARD, scopeSatisfies } from "./scopes.js";

export {
  CachingIssuerTrustMap,
  InMemoryIssuerTrustMap,
  type IssuerTrustMap,
  type TenantTrust,
} from "./trust.js";
