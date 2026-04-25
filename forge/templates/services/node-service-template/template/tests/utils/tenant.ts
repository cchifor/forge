/**
 * Tenant-context builders used in unit + integration tests.
 *
 * Mirrored across the three forge backends — see
 * docs/testing-generated-backends.md for the cross-language contract.
 */

export const DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001";
export const DEFAULT_CUSTOMER_ID = DEFAULT_USER_ID;
export const DEFAULT_EMAIL = "test@localhost";
export const DEFAULT_ROLES = ["user"];

export interface TenantTestContext {
	userId: string;
	customerId: string;
	email: string;
	roles: string[];
}

export function tenantFactory(
	overrides: Partial<TenantTestContext> = {},
): TenantTestContext {
	return {
		userId: overrides.userId ?? DEFAULT_USER_ID,
		customerId: overrides.customerId ?? overrides.userId ?? DEFAULT_USER_ID,
		email: overrides.email ?? DEFAULT_EMAIL,
		roles: overrides.roles ?? [...DEFAULT_ROLES],
	};
}

export function authenticatedHeaders(
	ctx: TenantTestContext = tenantFactory(),
): Record<string, string> {
	const headers: Record<string, string> = {
		"x-gatekeeper-user-id": ctx.userId,
		"x-gatekeeper-email": ctx.email,
		"x-gatekeeper-roles": ctx.roles.join(","),
	};
	if (ctx.customerId !== ctx.userId) {
		headers["x-customer-id"] = ctx.customerId;
	}
	return headers;
}
