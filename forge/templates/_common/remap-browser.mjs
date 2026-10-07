import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import coverage from 'istanbul-lib-coverage';
import sourceMaps from 'istanbul-lib-source-maps';

// Browser transforms instrument compiled SFCs. Map counters back to original
// Vue/Svelte/TypeScript lines before merging them with unit-suite coverage.
const [directory, destination] = process.argv.slice(2);
const merged = coverage.createCoverageMap({});
for (const name of await fs.readdir(directory)) {
  if (name.endsWith('.json')) {
    merged.merge(JSON.parse(await fs.readFile(path.join(directory, name), 'utf8')));
  }
}
const result = await sourceMaps.createSourceMapStore().transformCoverage(merged);
await fs.writeFile(destination, JSON.stringify(result.toJSON()));
