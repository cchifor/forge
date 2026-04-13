import { z } from 'zod'

export function paginatedResponseSchema<T extends z.ZodTypeAny>(itemSchema: T) {
  return z.object({
    items: z.array(itemSchema),
    total: z.number().int(),
    skip: z.number().int(),
    limit: z.number().int(),
    has_more: z.boolean().optional(),
  })
}

export const apiErrorSchema = z.object({
  message: z.string(),
  type: z.string(),
  detail: z.record(z.unknown()).nullable().optional(),
})

export type ApiErrorParsed = z.infer<typeof apiErrorSchema>
