import pino from "pino";
import { appConfig } from "../config/index.js";

export const logger = pino({
	level: appConfig.logging.level,
	transport: appConfig.logging.pretty
		? { target: "pino-pretty", options: { colorize: true } }
		: undefined,
});
