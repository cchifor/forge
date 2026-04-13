import { defineConfig } from '@hey-api/openapi-ts'

export default defineConfig({
  input: process.env.OPENAPI_SPEC || './openapi-snapshot.json',
  output: {
    path: 'src/shared/api/generated',
  },
  plugins: [
    {
      name: '@hey-api/typescript',
      enums: 'typescript',
    },
  ],
})
