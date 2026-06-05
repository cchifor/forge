import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Library build — emits an ESM bundle. Declarations are intentionally not
// emitted here (same as canvas-svelte): the canvas packages ship as vendored
// source, not as a published npm package, and vite-plugin-dts proved
// unreliable for .vue SFCs under the TS 6 / vite 8 toolchain (it needed an
// unhoisted @vue/language-core and stopped flattening output to dist/). Only
// canvas-core's declarations are actually consumed (canvas-vue type-checks
// against them) and those are emitted via tsc there. Vue and @ag-ui/client
// are externalised so the consuming app's copy is used (prevents duplicate
// Vue instances + double-registered @ag-ui/client state).
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    lib: {
      entry: fileURLToPath(new URL('./src/index.ts', import.meta.url)),
      name: 'ForgeCanvasVue',
      formats: ['es'],
      fileName: 'index',
    },
    rollupOptions: {
      external: ['vue', '@ag-ui/client', '@ag-ui/core'],
      output: {
        globals: {
          vue: 'Vue',
        },
      },
    },
    sourcemap: true,
    target: 'esnext',
  },
})
