import fs from "node:fs";
import path from "node:path";
import { parse as parseYaml } from "yaml";
import { AppConfigSchema, type AppConfig } from "./schema.js";

/**
 * RFC-008 layered config loader.
 *
 * Priority (highest wins):
 *   1. Env vars prefixed `APP__` (nested keys via `__`, e.g.
 *      `APP__SERVER__PORT=8080`).
 *   2. `.secrets.yaml` (gitignored; for local dev secrets).
 *   3. `config/<ENV>.yaml` (e.g. `config/production.yaml`), selected by
 *      `ENV` or `NODE_ENV`.
 *   4. `config/defaults.yaml`.
 *   5. Schema defaults encoded in `schema.ts`.
 */

type Json = string | number | boolean | null | Json[] | { [k: string]: Json };
type Dict = Record<string, Json>;

function readYamlIfExists(filePath: string): Dict {
	if (!fs.existsSync(filePath)) return {};
	const raw = fs.readFileSync(filePath, "utf-8");
	const parsed = parseYaml(raw);
	return (parsed ?? {}) as Dict;
}

function isObject(v: unknown): v is Dict {
	return typeof v === "object" && v !== null && !Array.isArray(v);
}

function deepMerge(target: Dict, override: Dict): Dict {
	const out: Dict = { ...target };
	for (const [key, value] of Object.entries(override)) {
		const current = out[key];
		if (isObject(current) && isObject(value)) {
			out[key] = deepMerge(current, value);
		} else {
			out[key] = value;
		}
	}
	return out;
}

function coerceScalar(raw: string): Json {
	if (raw === "true") return true;
	if (raw === "false") return false;
	if (raw === "null") return null;
	if (/^-?\d+$/.test(raw)) return Number(raw);
	if (/^-?\d+\.\d+$/.test(raw)) return Number(raw);
	if (raw.startsWith("[") || raw.startsWith("{")) {
		try {
			return JSON.parse(raw);
		} catch {
			/* fall through */
		}
	}
	return raw;
}

function envOverlay(env: NodeJS.ProcessEnv, prefix = "APP__"): Dict {
	const out: Dict = {};
	for (const [rawKey, rawVal] of Object.entries(env)) {
		if (rawVal === undefined || !rawKey.startsWith(prefix)) continue;
		const path = rawKey
			.slice(prefix.length)
			.split("__")
			.map((s) => s.toLowerCase());
		let cursor: Dict = out;
		for (let i = 0; i < path.length - 1; i++) {
			const key = path[i]!;
			const next = cursor[key];
			if (!isObject(next)) cursor[key] = {};
			cursor = cursor[key] as Dict;
		}
		cursor[path[path.length - 1]!] = coerceScalar(rawVal);
	}
	return out;
}

export interface LoadOptions {
	projectRoot?: string;
	env?: string;
	processEnv?: NodeJS.ProcessEnv;
}

export function loadConfig(options: LoadOptions = {}): AppConfig {
	const processEnv = options.processEnv ?? process.env;
	const env =
		options.env ??
		processEnv.ENV ??
		processEnv.NODE_ENV ??
		"development";
	const root = options.projectRoot ?? process.cwd();
	const configDir = path.join(root, "config");

	const layers = [
		readYamlIfExists(path.join(configDir, "defaults.yaml")),
		readYamlIfExists(path.join(configDir, `${env}.yaml`)),
		readYamlIfExists(path.join(root, ".secrets.yaml")),
		envOverlay(processEnv),
	];

	let merged: Dict = {};
	for (const layer of layers) merged = deepMerge(merged, layer);

	// Inject detected env as app.env if the layer stack didn't already.
	if (!isObject(merged.app)) merged.app = {};
	const appLayer = merged.app as Dict;
	if (typeof appLayer.env !== "string") appLayer.env = env;

	return AppConfigSchema.parse(merged);
}
