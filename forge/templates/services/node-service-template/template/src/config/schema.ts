import { z } from "zod";

/**
 * Canonical application config shared across Python / Node / Rust
 * backends. See docs/rfcs/RFC-008-config-loading.md for layer
 * precedence (env vars > secrets.yaml > <env>.yaml > defaults).
 */

export const CorsConfigSchema = z.object({
	enabled: z.boolean().default(true),
	allowOrigins: z.array(z.string()).default(["*"]),
	allowMethods: z.array(z.string()).default(["GET", "POST", "PATCH", "DELETE"]),
	allowHeaders: z.array(z.string()).default(["*"]),
	allowCredentials: z.boolean().default(false),
	maxAge: z.number().default(600),
});

export const ServerConfigSchema = z.object({
	host: z.string().default("0.0.0.0"),
	port: z.number().int().min(1).max(65535).default(5000),
	cors: CorsConfigSchema.default({}),
});

export const DbConfigSchema = z.object({
	url: z.string().min(1, "db.url is required"),
	poolMin: z.number().int().nonnegative().default(2),
	poolMax: z.number().int().positive().default(10),
	statementTimeoutMs: z.number().int().positive().default(30_000),
});

export const LoggingConfigSchema = z.object({
	level: z
		.enum(["trace", "debug", "info", "warn", "error", "fatal"])
		.default("info"),
	pretty: z.boolean().default(false),
});

export const AuthConfigSchema = z.object({
	enabled: z.boolean().default(false),
	serverUrl: z.string().optional(),
	realm: z.string().optional(),
	clientId: z.string().optional(),
});

export const SecurityConfigSchema = z.object({
	auth: AuthConfigSchema.default({}),
});

export const AppInfoSchema = z.object({
	name: z.string().default("service"),
	version: z.string().default("0.0.0"),
	env: z
		.enum(["development", "testing", "staging", "production"])
		.default("development"),
});

/**
 * Environments that are EXEMPT from the production fail-closed auth check.
 * Mirrors the Python ``SecurityConfig._reject_default_secret_in_prod``
 * exemption set so all three backends behave identically (WS-2.1 parity).
 */
const AUTH_GUARD_EXEMPT_ENVS = new Set([
	"development",
	"dev",
	"local",
	"test",
	"testing",
]);

/**
 * Fail closed in production-like environments when auth is enabled.
 *
 * The platform auth middleware reads the OIDC issuer/audience from the
 * ``GATEKEEPER_ISSUER`` / ``SERVICE_AUDIENCE`` env vars (NOT the loaded
 * config), and throws at bootstrap if they are missing. This guard surfaces
 * the same misconfiguration earlier — at config load — with a clear message,
 * before the server starts wiring middleware.
 *
 * Like the Python validator, the effective env is resolved from ``ENV`` /
 * ``NODE_ENV`` and defaults to ``production`` when unset (fail closed). Only
 * the explicit dev/test names above are exempt.
 */
export const AppConfigSchema = z
	.object({
		app: AppInfoSchema.default({}),
		server: ServerConfigSchema.default({}),
		db: DbConfigSchema,
		logging: LoggingConfigSchema.default({}),
		security: SecurityConfigSchema.default({}),
	})
	.superRefine((cfg, ctx) => {
		const env = (process.env.ENV ?? process.env.NODE_ENV ?? "production")
			.trim()
			.toLowerCase();
		if (AUTH_GUARD_EXEMPT_ENVS.has(env)) return;
		if (!cfg.security.auth.enabled) return;

		for (const varName of ["GATEKEEPER_ISSUER", "SERVICE_AUDIENCE"]) {
			const value = (process.env[varName] ?? "").trim();
			if (!value) {
				ctx.addIssue({
					code: z.ZodIssueCode.custom,
					path: ["security", "auth"],
					message:
						`${varName} is unset or blank but security.auth.enabled is true — ` +
						"set the real Gatekeeper issuer/audience before running in " +
						"production (the auth middleware reads these env vars).",
				});
			}
		}
	});

export type CorsConfig = z.infer<typeof CorsConfigSchema>;
export type ServerConfig = z.infer<typeof ServerConfigSchema>;
export type DbConfig = z.infer<typeof DbConfigSchema>;
export type LoggingConfig = z.infer<typeof LoggingConfigSchema>;
export type SecurityConfig = z.infer<typeof SecurityConfigSchema>;
export type AppConfig = z.infer<typeof AppConfigSchema>;
