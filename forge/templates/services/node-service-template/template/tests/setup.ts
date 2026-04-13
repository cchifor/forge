import { vi } from "vitest";

// Mock Prisma globally for unit tests
vi.mock("../src/lib/prisma.js", () => ({
	prisma: {
		item: {
			findMany: vi.fn(),
			findFirst: vi.fn(),
			findUnique: vi.fn(),
			create: vi.fn(),
			update: vi.fn(),
			delete: vi.fn(),
			count: vi.fn(),
		},
		$queryRaw: vi.fn(),
		$disconnect: vi.fn(),
	},
}));
