import { ZodError, type ZodSchema } from 'zod';
import { toast } from 'svelte-sonner';

export function reportValidationFailure(label: string, error: ZodError): void {
	const issues = error.issues.map((i) => `  ${i.path.join('.')}: ${i.message}`).join('\n');
	console.error(`[API Contract Violation] ${label}:\n${issues}`);
	toast.error(`Backend contract violation: ${label}`);
}

export async function validateResponse<T>(
	schema: ZodSchema<T>,
	data: unknown,
	label: string
): Promise<T> {
	try {
		return await schema.parseAsync(data);
	} catch (error) {
		if (error instanceof ZodError) {
			reportValidationFailure(label, error);
		}
		throw error;
	}
}
