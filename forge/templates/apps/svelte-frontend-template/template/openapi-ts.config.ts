import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
	client: false,
	input: process.env.OPENAPI_SPEC || './openapi-snapshot.json',
	output: {
		path: 'src/lib/core/api/generated',
		format: 'prettier'
	},
	types: {
		enums: 'typescript'
	},
	schemas: false
});
