// Runtime lint for canvas component props (Svelte variant).
// Mirrors packages/canvas-vue/src/lint.ts — keep them in sync.

export interface LintIssue {
  field: string
  message: string
}

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
    const enumValues = schema.enum as unknown[] | undefined
    if (enumValues && !enumValues.includes(value)) {
      issues.push({ field: name, message: `not in enum ${JSON.stringify(enumValues)}` })
    }
  }

  return issues
}

export function warnOnLintIssues(componentName: string, issues: LintIssue[]): void {
  if (issues.length === 0) return
  const isProd =
    // @ts-expect-error — Vite specific.
    (typeof import.meta !== 'undefined' && import.meta.env?.PROD === true) ||
    (typeof process !== 'undefined' && process.env?.NODE_ENV === 'production')
  if (isProd) return
  // eslint-disable-next-line no-console
  console.warn(
    `[forge:canvas] ${componentName}: ${issues.length} prop lint issue(s)`,
    issues,
  )
}
