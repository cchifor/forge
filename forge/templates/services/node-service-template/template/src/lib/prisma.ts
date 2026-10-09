import { PrismaClient } from "@prisma/client";
import { PrismaPg } from "@prisma/adapter-pg";
import { databaseConnectionOptions } from "./prisma-options.js";

const adapterOptions = databaseConnectionOptions(process.env.DATABASE_URL);
const schema = process.env.DATABASE_URL
	? (new URL(process.env.DATABASE_URL).searchParams.get("schema") ?? undefined)
	: undefined;

// FORGE:PRISMA_CLIENT_INIT
// Fragments injecting a connection-pool helper (e.g.
// reliability_connection_pool) target this anchor.

const globalForPrisma = globalThis as unknown as {
	prisma: PrismaClient | undefined;
};

export const prisma =
	globalForPrisma.prisma ??
	new PrismaClient({ adapter: new PrismaPg(adapterOptions, { schema }) });

if (process.env.NODE_ENV !== "production") {
	globalForPrisma.prisma = prisma;
}
