/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string
  readonly VITE_AUTH_DISABLED: string
  readonly VITE_KEYCLOAK_URL: string
  readonly VITE_KEYCLOAK_REALM: string
  readonly VITE_KEYCLOAK_CLIENT_ID: string
  readonly VITE_MSW_ENABLED: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare const __DEV_VALIDATION__: boolean
