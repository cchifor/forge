import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'

// Library build for the framework-agnostic core. Vite emits the ESM bundle;
// declarations are emitted separately by `tsc --emitDeclarationOnly` in the
// build script (see package.json). vite-plugin-dts proved unreliable here —
// across the TS 6 + vite-plugin-dts 5 bumps it variously broke type rollup
// and stopped flattening output to dist/ (emitting dist/src/ instead), which
// silently shipped a package whose "types": "./dist/index.d.ts" pointed at a
// missing file. canvas-core's declarations ARE consumed (canvas-vue type-
// checks against them), so they must land reliably; tsc is deterministic.
// @ag-ui/core is externalised — the consuming framework adapter pulls its own
// copy. fast-json-patch is bundled (no peer dep needed by consumers).
export default defineConfig({
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
