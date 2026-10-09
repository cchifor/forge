/** Preserve Prisma URL pool settings when using the native pg adapter. */
export function databaseConnectionOptions(base?: string) {
	if (!base) return { connectionString: base, connectionTimeoutMillis: 5_000 };
	const url = new URL(base);
	const limit = url.searchParams.get("connection_limit");
	const timeout = url.searchParams.get("pool_timeout");
	const max = limit === null ? undefined : Number(limit);
	const timeoutSeconds = timeout === null ? 5 : Number(timeout);
	if (max !== undefined && (!Number.isInteger(max) || max < 1)) {
		throw new Error("Prisma connection_limit must be a positive integer");
	}
	if (
		timeout === "" ||
		!Number.isFinite(timeoutSeconds) ||
		timeoutSeconds < 0
	) {
		throw new Error("Prisma pool_timeout must be a nonnegative number");
	}
	url.searchParams.delete("connection_limit");
	url.searchParams.delete("pool_timeout");
	return {
		connectionString: url.toString(),
		...(max === undefined ? {} : { max }),
		connectionTimeoutMillis: timeoutSeconds * 1000,
	};
}
