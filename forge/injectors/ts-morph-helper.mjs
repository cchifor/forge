#!/usr/bin/env node
/**
 * ts-morph subprocess helper for forge.
 *
 * Invoked by forge/injectors/ts_morph_sidecar.py via stdin JSON:
 *
 *   {
 *     "op": "inject",
 *     "file": "/abs/path/to/main.ts",
 *     "tag": "rate_limit:MIDDLEWARE",
 *     "marker": "MIDDLEWARE",
 *     "snippet": "app.register(rateLimit);",
 *     "position": "after"
 *   }
 *
 * Writes the mutated file in place. Prints JSON status on stdout:
 *   {"ok": true, "file": "...", "replaced": false}
 *
 * Failures come back as:
 *   {"ok": false, "error": "<message>"}
 *
 * Requires ts-morph installed: `npm install --save-dev ts-morph`.
 * ts-morph is NOT a forge runtime dep; generated projects (which may
 * never need AST-level injection) don't pay for it. Users who opt in
 * by setting FORGE_TS_AST=1 must have ts-morph on NODE_PATH.
 */

import { readFile, writeFile } from "node:fs/promises";
import { createInterface } from "node:readline";

async function loadProject(filePath) {
  try {
    const { Project } = await import("ts-morph");
    const project = new Project({ useInMemoryFileSystem: false });
    return project.addSourceFileAtPath(filePath);
  } catch (err) {
    throw new Error(
      `ts-morph not available: ${err.message}. ` +
        `Install with 'npm install ts-morph' and re-run with FORGE_TS_AST=1.`,
    );
  }
}

function findAnchorLine(sourceText, markerName) {
  const lines = sourceText.split("\n");
  const anchorRe = new RegExp(`//\\s*forge:anchor\\s+(\\S+)`);
  const legacyRe = new RegExp(`//\\s*FORGE:${markerName.toUpperCase()}\\b`);
  const sentinelBeginRe = /\/\/\s*FORGE:BEGIN\s/;
  const sentinelEndRe = /\/\/\s*FORGE:END\s/;

  const normalized = markerName.toLowerCase().replace(/:/g, "");
  const hits = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (sentinelBeginRe.test(line) || sentinelEndRe.test(line)) continue;
    const m = line.match(anchorRe);
    if (m && m[1].toLowerCase() === normalized) {
      hits.push(i);
      continue;
    }
    if (legacyRe.test(line)) {
      hits.push(i);
    }
  }
  if (hits.length === 0) return -1;
  if (hits.length > 1) throw new Error(`Anchor ${markerName!r} appears on multiple lines`);
  return hits[0];
}

function findSentinelBlock(sourceText, tag) {
  const lines = sourceText.split("\n");
  let begin = -1;
  let end = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes(`// FORGE:BEGIN ${tag}`)) begin = i;
    if (lines[i].includes(`// FORGE:END ${tag}`)) {
      end = i;
      break;
    }
  }
  return [begin, end];
}

function leadingIndent(line) {
  const m = line.match(/^[ \t]*/);
  return m ? m[0] : "";
}

function renderBlock(indent, tag, snippet) {
  const begin = `${indent}// FORGE:BEGIN ${tag}`;
  const end = `${indent}// FORGE:END ${tag}`;
  const body = snippet
    .split("\n")
    .map((raw) => `${indent}${raw}`)
    .join("\n");
  return `${begin}\n${body}\n${end}`;
}

async function doInject(req) {
  const sourceText = await readFile(req.file, "utf-8");
  const lines = sourceText.split("\n");

  const [beginIdx, endIdx] = findSentinelBlock(sourceText, req.tag);
  if (beginIdx >= 0 && endIdx >= 0) {
    const indent = leadingIndent(lines[beginIdx]);
    const fresh = renderBlock(indent, req.tag, req.snippet);
    const mutated = [
      ...lines.slice(0, beginIdx),
      ...fresh.split("\n"),
      ...lines.slice(endIdx + 1),
    ].join("\n");
    await writeFile(req.file, mutated, "utf-8");
    return { ok: true, file: req.file, replaced: true };
  }

  // Confirm the source parses as valid TypeScript before a fresh injection.
  await loadProject(req.file);

  const anchorIdx = findAnchorLine(sourceText, req.marker);
  if (anchorIdx < 0) {
    throw new Error(`Anchor for ${req.marker} not found in ${req.file}`);
  }
  const indent = leadingIndent(lines[anchorIdx]);
  const block = renderBlock(indent, req.tag, req.snippet);
  const insertAt = req.position === "after" ? anchorIdx + 1 : anchorIdx;
  const mutated = [...lines.slice(0, insertAt), ...block.split("\n"), ...lines.slice(insertAt)].join("\n");
  await writeFile(req.file, mutated, "utf-8");
  return { ok: true, file: req.file, replaced: false };
}

async function main() {
  const rl = createInterface({ input: process.stdin });
  const lines = [];
  for await (const line of rl) lines.push(line);
  let req;
  try {
    req = JSON.parse(lines.join("\n"));
  } catch (e) {
    console.log(JSON.stringify({ ok: false, error: `bad JSON: ${e.message}` }));
    process.exit(1);
  }
  try {
    const result = await doInject(req);
    console.log(JSON.stringify(result));
  } catch (e) {
    console.log(JSON.stringify({ ok: false, error: e.message }));
    process.exit(1);
  }
}

main();
