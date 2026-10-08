import { mergeConfig } from 'vitest/config';
import base from './vitest.config';
const config = mergeConfig(base, {});
config.resolve = { ...config.resolve, conditions: ['browser'] };
config.test!.include = ['tests/integration/**/*.test.ts'];
config.test!.passWithNoTests = false;
export default config;
