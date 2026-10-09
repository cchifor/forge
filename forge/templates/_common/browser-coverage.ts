import path from 'node:path';
import { createInstrumenter } from 'istanbul-lib-instrument';
import type { Plugin } from 'vite';

/** Instrument compiler output with its real source map, never synthetic line positions. */
export default function browserCoverage(): Plugin {
  let sourceRoot = '';
  const instrumenter = createInstrumenter({
    coverageGlobalScope: 'globalThis',
    coverageGlobalScopeFunc: false,
    produceSourceMap: true,
    preserveComments: true,
    esModules: true,
    autoWrap: true,
  });
  return {
    name: 'forge:browser-coverage',
    apply: 'serve',
    enforce: 'post',
    configResolved(config) {
      sourceRoot = path.resolve(config.root, 'src').replaceAll('\\', '/') + '/';
    },
    transform(code, id, options) {
      if (options?.ssr || id.startsWith('\0')) return;
      const filename = id.split('?')[0].replaceAll('\\', '/');
      if (!filename.startsWith(sourceRoot) || !/\.(?:[cm]?[jt]sx?|vue|svelte)$/.test(filename)) return;
      if (/\.(?:test|spec|d)\.[cm]?[jt]sx?$/.test(filename) || filename.startsWith(sourceRoot + 'test/')) return;
      if (/[?&]type=style(?:&|$)/.test(id) || /import _sfc_main from/.test(code)) return;
      // Istanbul's source-map 0.6 types declare version as string; V3 maps use number.
      // Preserve the compiler map unchanged across this declaration-only mismatch.
      const sourceMap = this.getCombinedSourcemap() as unknown as Parameters<
        typeof instrumenter.instrumentSync
      >[2];
      const instrumented = instrumenter.instrumentSync(code, filename, sourceMap);
      return { code: instrumented, map: JSON.stringify(instrumenter.lastSourceMap()) };
    },
  };
}
