import { vitePreprocess } from '@sveltejs/vite-plugin-svelte'

// Library build config — not a SvelteKit app, so no kit adapter.
export default {
  preprocess: vitePreprocess(),
  compilerOptions: {
    runes: true,
  },
}
