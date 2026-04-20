import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// Library build for Svelte 5 — emits ESM + source maps. Svelte itself
// is externalised; the consuming SvelteKit/Vite app supplies it.
export default defineConfig({
  plugins: [svelte()],
  build: {
    lib: {
      entry: fileURLToPath(new URL('./src/index.ts', import.meta.url)),
      name: 'ForgeCanvasSvelte',
      formats: ['es'],
      fileName: 'index',
    },
    rollupOptions: {
      external: ['svelte', '@ag-ui/client', '@ag-ui/core'],
    },
    sourcemap: true,
    target: 'esnext',
  },
})
