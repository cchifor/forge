import { z } from "zod";

export const PaginationQuery = z.object({
	skip: z.coerce.number().int().min(0).default(0),
	limit: z.coerce.number().int().min(1).max(200).default(50),
});

export type PaginationQuery = z.infer<typeof PaginationQuery>;

export const ErrorResponse = z.object({
	statusCode: z.number(),
	error: z.string(),
	message: z.string(),
});

export type ErrorResponse = z.infer<typeof ErrorResponse>;

export function paginatedSchema<T extends z.ZodType>(itemSchema: T) {
	return z.object({
		items: z.array(itemSchema),
		total: z.number(),
		skip: z.number(),
		limit: z.number(),
		has_more: z.boolean(),
	});
}
