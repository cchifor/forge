import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		adapter: adapter({
			fallback: 'index.html'
		}),
		// canvas-core is vendored into src/lib/features/chat/canvas-core/ (not a
		// published package); alias the `@forge/canvas-core` specifier to it.
		alias: {
			'@forge/canvas-core': 'src/lib/features/chat/canvas-core/index.ts'
		}
	}
};

export default config;
