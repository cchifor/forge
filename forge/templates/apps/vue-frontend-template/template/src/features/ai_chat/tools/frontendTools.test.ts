import { describe, it, expect } from 'vitest'
import {
  FRONTEND_TOOLS,
  FRONTEND_TOOL_NAMES,
  FRONTEND_TOOL_COMPONENT_MAP,
  DISPLAY_ONLY_FRONTEND_TOOLS,
  type FrontendTool,
} from './frontendTools'

function asObject(v: unknown): Record<string, unknown> {
  expect(v && typeof v === 'object' && !Array.isArray(v)).toBe(true)
  return v as Record<string, unknown>
}

describe('FRONTEND_TOOLS', () => {
  it('exposes exactly the three generic v1 tools', () => {
    expect(FRONTEND_TOOLS.map((t) => t.name)).toEqual([
      'show_dynamic_form',
      'show_data_table',
      'show_approval',
    ])
  })

  it('every tool has a non-empty neutral description and JSON-schema parameters', () => {
    for (const tool of FRONTEND_TOOLS) {
      expect(typeof tool.name).toBe('string')
      expect(tool.description.length).toBeGreaterThan(0)
      const params = asObject(tool.parameters)
      expect(params.type).toBe('object')
      expect(asObject(params.properties)).toBeTruthy()
      expect(Array.isArray(params.required)).toBe(true)
      // neutral wording — no platform-domain coupling leaked into descriptions
      expect(tool.description.toLowerCase()).not.toMatch(/workflow|data.?source|integration/)
    }
  })

  it('show_dynamic_form requires title + fields and defines field enum types', () => {
    const tool = FRONTEND_TOOLS.find((t) => t.name === 'show_dynamic_form') as FrontendTool
    const params = asObject(tool.parameters)
    expect(params.required).toEqual(['title', 'fields'])
    const props = asObject(params.properties)
    const fields = asObject(props.fields)
    const items = asObject(fields.items)
    const fieldProps = asObject(items.properties)
    const typeProp = asObject(fieldProps.type)
    expect(typeProp.enum).toEqual([
      'text',
      'password',
      'url',
      'email',
      'number',
      'textarea',
      'select',
      'toggle',
      'checkbox-group',
    ])
    expect(items.required).toEqual(['name', 'label', 'type'])
  })

  it('show_data_table requires title + columns + rows', () => {
    const tool = FRONTEND_TOOLS.find((t) => t.name === 'show_data_table') as FrontendTool
    const params = asObject(tool.parameters)
    expect(params.required).toEqual(['title', 'columns', 'rows'])
    const props = asObject(params.properties)
    const columns = asObject(props.columns)
    const colItems = asObject(columns.items)
    expect(colItems.required).toEqual(['key', 'label'])
  })

  it('show_approval requires title + message', () => {
    const tool = FRONTEND_TOOLS.find((t) => t.name === 'show_approval') as FrontendTool
    const params = asObject(tool.parameters)
    expect(params.required).toEqual(['title', 'message'])
  })
})

describe('derived exports', () => {
  it('FRONTEND_TOOL_NAMES matches the tool list', () => {
    expect(FRONTEND_TOOL_NAMES).toEqual(new Set(FRONTEND_TOOLS.map((t) => t.name)))
    expect(FRONTEND_TOOL_NAMES.size).toBe(FRONTEND_TOOLS.length)
  })

  it('FRONTEND_TOOL_COMPONENT_MAP has exactly one activityType per tool', () => {
    expect(Object.keys(FRONTEND_TOOL_COMPONENT_MAP).sort()).toEqual(
      [...FRONTEND_TOOL_NAMES].sort(),
    )
    expect(FRONTEND_TOOL_COMPONENT_MAP).toEqual({
      show_dynamic_form: 'dynamic_form',
      show_data_table: 'data_table',
      show_approval: 'approval',
    })
    // every mapped name is a real tool
    for (const name of Object.keys(FRONTEND_TOOL_COMPONENT_MAP)) {
      expect(FRONTEND_TOOL_NAMES.has(name)).toBe(true)
    }
  })

  it('DISPLAY_ONLY_FRONTEND_TOOLS is empty (all three tools are interactive)', () => {
    expect(DISPLAY_ONLY_FRONTEND_TOOLS.size).toBe(0)
  })
})
