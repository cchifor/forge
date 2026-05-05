import js from '@eslint/js'
import tsPlugin from '@typescript-eslint/eslint-plugin'
import tsParser from '@typescript-eslint/parser'
import vuePlugin from 'eslint-plugin-vue'
import vueParser from 'vue-eslint-parser'

// eslint-plugin-vue 10.x ships flat configs as ``configs['flat/<name>']``;
// the legacy ``configs['vue3-recommended']`` namespace was dropped. Pull
// the recommended rules out of the flat config object so we can spread
// them into our own block alongside the TS / Vue parser overrides.
const vueRecommendedRules = (
  vuePlugin.configs['flat/recommended'] ?? []
).reduce((acc, entry) => {
  if (entry && typeof entry === 'object' && entry.rules) {
    Object.assign(acc, entry.rules)
  }
  return acc
}, {})

export default [
  js.configs.recommended,
  {
    files: ['**/*.ts', '**/*.tsx'],
    languageOptions: {
      parser: tsParser,
      parserOptions: { ecmaVersion: 'latest', sourceType: 'module' },
    },
    plugins: { '@typescript-eslint': tsPlugin },
    rules: {
      ...tsPlugin.configs.recommended.rules,
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
    },
  },
  {
    files: ['**/*.vue'],
    languageOptions: {
      parser: vueParser,
      parserOptions: { parser: tsParser, ecmaVersion: 'latest', sourceType: 'module' },
    },
    plugins: { vue: vuePlugin },
    rules: {
      ...vueRecommendedRules,
      'vue/multi-word-component-names': 'off',
    },
  },
  { ignores: ['dist/', 'node_modules/', 'src/api/generated/', 'src/auto-imports.d.ts'] },
]
