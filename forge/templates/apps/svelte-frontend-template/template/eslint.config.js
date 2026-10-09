import js from '@eslint/js';
import globals from 'globals';
import ts from 'typescript-eslint';
import svelte from 'eslint-plugin-svelte';
import svelteParser from 'svelte-eslint-parser';

export default [
	js.configs.recommended,
	{ languageOptions: { globals: { ...globals.browser, ...globals.node } } },
	...ts.configs.recommended,
	...svelte.configs['flat/recommended'],
	{
		files: ['**/*.svelte', '**/*.svelte.ts'],
		languageOptions: {
			parser: svelteParser,
			parserOptions: {
				parser: ts.parser
			}
		}
	},
	{
		rules: {
			'@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }]
		}
	},
	{
		// Protocol emitters deliberately preserve open, dynamic JSON payload types.
		files: ['src/lib/features/chat/ui_protocol.gen.ts', 'src/lib/features/chat/events.gen.ts'],
		rules: { '@typescript-eslint/no-explicit-any': 'off' }
	},
	{
		ignores: ['build/', '.svelte-kit/', 'node_modules/', 'src/api/generated/']
	}
];
