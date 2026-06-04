import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import dts from 'vite-plugin-dts'

// Library build for the framework-agnostic core. Mirrors the canvas-vue
// / canvas-svelte build setup (Vite library mode + vite-plugin-dts) so
// publishing + consumption stays consistent across the three packages.
// @ag-ui/core is externalised — the consuming framework adapter pulls
// its own copy. fast-json-patch is bundled (no peer dep needed by
// consumers).
export default defineConfig({
  plugins: [
    dts({
      include: ['src/**/*.ts'],
      outDir: 'dist',
      // vite-plugin-dts 5 no longer infers the entry root, so without this
      // it emits declarations under dist/src/ (e.g. dist/src/index.d.ts)
      // instead of dist/, breaking the package's "types":
      // "./dist/index.d.ts" entry — consumers then fail with TS7016
      // "could not find a declaration file". Flatten to dist/ like v4 did.
      entryRoot: 'src',
      staticImport: true,
      rollupTypes: false,
    }),
  ],
  build: {
    lib: {
      entry: fileURLToPath(new URL('./src/index.ts', import.meta.url)),
      name: 'ForgeCanvasCore',
      formats: ['es'],
      fileName: 'index',
    },
    rollupOptions: {
      external: ['@ag-ui/core'],
    },
    sourcemap: true,
    target: 'esnext',
  },
  test: {
    environment: 'jsdom',
    globals: false,
    include: ['tests/**/*.test.ts'],
  },
})
