export { loadConfig } from "./loader.js";
export * from "./schema.js";

import { loadConfig } from "./loader.js";

/**
 * Eagerly-loaded application config. Imported modules can use this
 * directly; tests that need to swap config should call `loadConfig`
 * with explicit `processEnv` / `env` overrides instead.
 */
export const appConfig = loadConfig();
