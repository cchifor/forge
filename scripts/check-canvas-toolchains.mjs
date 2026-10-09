// Verify the compiler each workspace/tool actually resolves after npm ci.
// Vue and Svelte still need the TypeScript 6 JavaScript API (see #357).
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { execFileSync } from 'node:child_process'
import { dirname, resolve } from 'node:path'

for (const [workspace, major] of [
  ['canvas-core', 7],
  ['canvas-vue', 6],
  ['canvas-svelte', 6],
]) {
  const require = createRequire(new URL(`../packages/${workspace}/package.json`, import.meta.url))
  const manifest = require('typescript/package.json')
  assert.equal(Number(manifest.version.split('.')[0]), major, `${workspace}: wrong compiler major`)

  const compiler = resolve(dirname(require.resolve('typescript/package.json')), manifest.bin.tsc)
  const version = execFileSync(process.execPath, [compiler, '--version'], { encoding: 'utf8' }).trim()
  assert.equal(version, `Version ${manifest.version}`, `${workspace}: compiler version mismatch`)
  console.log(`${workspace}: ${version}`)

  const tools = workspace === 'canvas-vue'
    ? ['vue-tsc', '@vue/compiler-sfc']
    : workspace === 'canvas-svelte' ? ['svelte-check'] : []
  for (const tool of tools) {
    const toolRequire = createRequire(require.resolve(tool))
    const ts = toolRequire('typescript')
    assert.equal(Number(ts.version.split('.')[0]), 6, `${tool}: needs the TypeScript 6 API`)
    assert.equal(typeof ts.createProgram, 'function', `${tool}: missing compiler API`)
    assert.equal(typeof ts.sys?.readFile, 'function', `${tool}: missing compiler filesystem`)
    console.log(`  ${tool}: TypeScript ${ts.version} JavaScript API`)
  }
}
