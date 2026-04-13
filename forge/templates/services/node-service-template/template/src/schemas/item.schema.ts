import { z } from "zod";
import { paginatedSchema } from "./common.schema.js";

export const ItemStatus = z.enum(["DRAFT", "ACTIVE", "ARCHIVED"]);
export type ItemStatus = z.infer<typeof ItemStatus>;

export const ItemCreate = z.object({
	name: z.string().min(1).max(255),
	description: z.string().nullish(),
	tags: z.array(z.string()).default([]),
	status: ItemStatus.default("DRAFT"),
});
export type ItemCreate = z.infer<typeof ItemCreate>;

export const ItemUpdate = z.object({
	name: z.string().min(1).max(255).optional(),
	description: z.string().nullish(),
	tags: z.array(z.string()).optional(),
	status: ItemStatus.optional(),
});
export type ItemUpdate = z.infer<typeof ItemUpdate>;

export const Item = z.object({
	id: z.string().uuid(),
	customer_id: z.string(),
	user_id: z.string(),
	name: z.string(),
	description: z.string().nullable(),
	tags: z.array(z.string()),
	status: ItemStatus,
	created_at: z.coerce.date(),
	updated_at: z.coerce.date(),
});
export type Item = z.infer<typeof Item>;

export const PaginatedItems = paginatedSchema(Item);
export type PaginatedItems = z.infer<typeof PaginatedItems>;
