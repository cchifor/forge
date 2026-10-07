import istanbul from 'vite-plugin-istanbul';
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
	plugins: [sveltekit(), tailwindcss(), ...(process.env.FORGE_COVERAGE === 'true' ? [istanbul({ include: 'src/**/*', exclude: ['**/*.test.*', '**/*.spec.*', 'src/test/**'], extension: ['.ts', '.vue', '.svelte'], requireEnv: false, forceBuildInstrument: false })] : [])],
	server: {
		port: 5173,
		proxy: {
			'/api': {
				target: 'http://localhost:5000',
				changeOrigin: true
			}
		}
	},
	test: {
		include: ['src/**/*.{test,spec}.{js,ts}'],
		globals: true,
		environment: 'jsdom',
		setupFiles: ['./src/test/setup.ts']
	}
});
