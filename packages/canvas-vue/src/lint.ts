// Runtime lint for canvas component props.
//
// Dev-mode only: compares backend-supplied props against the component's
// registered JSON Schema and emits `console.warn` on each mismatch so
// prop drift (backend adding a field, frontend not updated) surfaces
// immediately in the browser console instead of silently rendering
// undefined.
//
// Production builds compile with `import.meta.env.PROD === true`, at which
// point the function short-circuits to a no-op (tree-shakable). Tests
// exercise the dev path directly.

export interface LintIssue {
  field: string
  message: string
}

/**
 * Validate `props` against a canvas component's declared JSON Schema.
 * Returns an empty array when the props are OK.
 *
 * This is intentionally shallow — only top-level property types +
 * required fields + additionalProperties are checked. Nested objects and
 * arrays pass through without recursion; match the backend's canvas
 * contract lint (`forge --canvas lint`) which is also shallow for 1.0.
 */
export function lintProps(
  propsSchema: Record<string, unknown> | undefined,
  props: Record<string, unknown>,
): LintIssue[] {
  if (!propsSchema) return []
  const issues: LintIssue[] = []
  const properties = (propsSchema.properties as Record<string, Record<string, unknown>>) || {}
  const required = (propsSchema.required as string[]) || []
  const additionalOk = propsSchema.additionalProperties === true

  for (const name of required) {
    if (!(name in props)) {
      issues.push({ field: name, message: 'required prop is missing' })
    }
  }

  for (const [name, value] of Object.entries(props)) {
    const schema = properties[name]
    if (!schema) {
      if (!additionalOk) {
        issues.push({ field: name, message: 'unknown prop' })
      }
      continue
    }
    const ty = schema.type as string | undefined
    if (ty === 'string' && typeof value !== 'string') {
      issues.push({ field: name, message: `expected string, got ${typeof value}` })
    } else if (ty === 'integer') {
      if (typeof value !== 'number' || !Number.isInteger(value)) {
        issues.push({ field: name, message: `expected integer, got ${typeof value}` })
      }
    } else if (ty === 'number' && typeof value !== 'number') {
      issues.push({ field: name, message: `expected number, got ${typeof value}` })
    } else if (ty === 'boolean' && typeof value !== 'boolean') {
      issues.push({ field: name, message: `expected boolean, got ${typeof value}` })
    } else if (ty === 'array' && !Array.isArray(value)) {
      issues.push({ field: name, message: `expected array, got ${typeof value}` })
    } else if (ty === 'object' && (typeof value !== 'object' || Array.isArray(value) || value === null)) {
      issues.push({ field: name, message: `expected object, got ${typeof value}` })
    }
    // Enum check
    const enumValues = schema.enum as unknown[] | undefined
    if (enumValues && !enumValues.includes(value)) {
      issues.push({ field: name, message: `not in enum ${JSON.stringify(enumValues)}` })
    }
  }

  return issues
}

/**
 * Warn about prop drift via console.warn in dev mode. No-op in prod.
 */
export function warnOnLintIssues(componentName: string, issues: LintIssue[]): void {
  if (issues.length === 0) return
  // Vite sets import.meta.env.PROD; fall back to process.env.NODE_ENV so
  // non-Vite builds (Webpack, Rspack, etc.) still get the dev-mode warn.
  const isProd =
    // @ts-ignore — import.meta.env is Vite-specific; guard at runtime.
    (typeof import.meta !== 'undefined' && import.meta.env?.PROD === true) ||
    (typeof process !== 'undefined' && process.env?.NODE_ENV === 'production')
  if (isProd) return
  // eslint-disable-next-line no-console
  console.warn(
    `[forge:canvas] ${componentName}: ${issues.length} prop lint issue(s)`,
    issues,
  )
}
