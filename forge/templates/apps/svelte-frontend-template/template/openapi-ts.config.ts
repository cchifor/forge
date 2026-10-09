import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
	input: process.env.OPENAPI_SPEC || './openapi-snapshot.json',
	output: {
		path: 'src/custom/api',
		postProcess: ['prettier']
	},
	plugins: [{ name: '@hey-api/typescript', enums: 'typescript' }]
});
