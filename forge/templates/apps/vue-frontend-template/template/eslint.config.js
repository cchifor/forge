import js from '@eslint/js'
import globals from 'globals'
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

// Browser + Node + Vitest globals. ``js.configs.recommended`` turns on
// ``no-undef``, which otherwise flags every DOM/runtime global (window,
// document, Location, timers, fetch, …) in app code, ``process`` in
// vite.config / scripts, and the Vitest globals in ``*.test.ts``. Sourced
// from the ``globals`` package so the list stays correct as the DOM/Node
// surface grows; shared across the TS and Vue blocks below.
const sharedGlobals = {
  ...globals.browser,
  ...globals.node,
  // The ``globals`` package has no ``vitest`` preset; declare the handful the
  // generated ``*.test.ts`` files use as test-runner globals.
  describe: 'readonly',
  it: 'readonly',
  test: 'readonly',
  expect: 'readonly',
  vi: 'readonly',
  beforeEach: 'readonly',
  afterEach: 'readonly',
  beforeAll: 'readonly',
  afterAll: 'readonly',
}

export default [
  js.configs.recommended,
  {
    rules: {
      // Generated code uses intentional empty ``catch {}`` blocks for
      // best-effort cleanup (e.g. swallowing a localStorage write that the
      // browser blocked in private mode).
      'no-empty': ['error', { allowEmptyCatch: true }],
    },
  },
  {
    files: ['**/*.ts', '**/*.tsx'],
    languageOptions: {
      parser: tsParser,
      parserOptions: { ecmaVersion: 'latest', sourceType: 'module' },
      globals: sharedGlobals,
    },
    plugins: { '@typescript-eslint': tsPlugin },
    rules: {
      ...tsPlugin.configs.recommended.rules,
      // Defer unused-var checking to @typescript-eslint (it understands types,
      // enums and overloads) and let ``_``-prefixed bindings opt out. The base
      // ``no-unused-vars`` from js.configs.recommended would otherwise error on
      // every intentional ``_`` placeholder the generator emits.
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      // The contract / UI-protocol codegen (``*.gen.ts``, ``ui-protocol/types.ts``)
      // and the AG-UI bridge model dynamic, server-driven shapes as ``any`` by
      // design, so the rule is advisory rather than an error here.
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
  {
    files: ['**/*.vue'],
    languageOptions: {
      parser: vueParser,
      parserOptions: { parser: tsParser, ecmaVersion: 'latest', sourceType: 'module' },
      globals: sharedGlobals,
    },
    plugins: { vue: vuePlugin },
    rules: {
      ...vueRecommendedRules,
      'vue/multi-word-component-names': 'off',
      // Pure formatting rules — these are a Prettier/editor concern, not a lint
      // gate. Left on, vue/recommended emits hundreds of advisory warnings on
      // the generated templates' markup; off, ``npm run lint`` stays signal.
      'vue/max-attributes-per-line': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/html-self-closing': 'off',
      // ``vue/comment-directive`` mis-reports ``clear``/unused-disable errors on
      // ordinary template comments under flat config + vue-eslint-parser 10.x.
      // It guards eslint-disable directives, which generated templates don't use.
      'vue/comment-directive': 'off',
      'no-unused-vars': 'off',
    },
  },
  { ignores: ['dist/', 'node_modules/', 'src/api/generated/', 'src/auto-imports.d.ts'] },
]
