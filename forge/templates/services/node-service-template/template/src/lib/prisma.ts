import { PrismaClient } from "@prisma/client";

const prismaOptions: ConstructorParameters<typeof PrismaClient>[0] = {};

// FORGE:PRISMA_CLIENT_INIT
// Fragments injecting a connection-pool helper (e.g.
// reliability_connection_pool) target this anchor.

const globalForPrisma = globalThis as unknown as { prisma: PrismaClient | undefined };

export const prisma = globalForPrisma.prisma ?? new PrismaClient(prismaOptions);

if (process.env.NODE_ENV !== "production") {
	globalForPrisma.prisma = prisma;
}
