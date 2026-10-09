import type { Path } from '$app/types';

/** Normalize a runtime internal URL before passing its app-relative path to resolve(). */
export function appPath(input: string, basePath = '/'): Path {
  const origin = 'https://forge.invalid';
  const base = new URL(basePath, origin).pathname.replace(/\/$/, '');
  let target: URL;
  try { target = new URL(input, origin); } catch { return ''; }
  if (target.origin !== origin || (base && target.pathname !== base && !target.pathname.startsWith(`${base}/`))) {
    return '';
  }
  // Runtime URLs cannot be represented by the generated static route union.
  // Keep their query/hash only after checking the origin and app base boundary.
  return `${target.pathname.slice(base.length).replace(/^\//, '')}${target.search}${target.hash}` as Path;
}
