declare global {
	namespace App {
		// interface Error {}
		// interface Locals {}
		// interface PageData {}
		// interface PageState {}
		// interface Platform {}
	}
}

interface ImportMetaEnv {
	readonly VITE_API_BASE_URL: string;
	readonly VITE_AUTH_DISABLED: string;
	readonly VITE_KEYCLOAK_URL: string;
	readonly VITE_KEYCLOAK_REALM: string;
	readonly VITE_KEYCLOAK_CLIENT_ID: string;
	readonly VITE_ENABLE_MOCKS: string;
}

interface ImportMeta {
	readonly env: ImportMetaEnv;
}

export {};
