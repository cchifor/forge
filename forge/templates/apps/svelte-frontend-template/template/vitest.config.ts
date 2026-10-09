import { mergeConfig, defineConfig } from 'vitest/config';
import base from './vite.config.ts';
export default mergeConfig(base, defineConfig({ resolve: { conditions: ['browser'] }, test: {
  include: ['src/**/*.{test,spec}.{js,ts}'], passWithNoTests: false,
  coverage: { provider: 'v8', include: ['src/**/*.{ts,svelte}'], exclude: ['src/test/**', '**/*.{test,spec}.ts', '**/*.d.ts'], reporter: ['json', 'lcov', 'text'] }
} }));
