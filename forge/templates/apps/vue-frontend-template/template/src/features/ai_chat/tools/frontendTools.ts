/**
 * Frontend tool definitions for the AG-UI ExternalToolset mechanism.
 *
 * These tools are sent in `RunAgentInput.tools` so the agent can call them.
 * When the agent calls a frontend tool, the run is interrupted with
 * `DeferredToolRequests.calls` and the frontend renders the corresponding
 * canvas component. The user's response is sent back via
 * `DeferredToolResults.calls` to resume the agent.
 *
 * `parameters` is a raw JSON-Schema object (not zod) so the shapes can be
 * forwarded verbatim to the agent transport.
 */

export interface FrontendTool {
  name: string
  description: string
  parameters: Record<string, unknown>
}

export const FRONTEND_TOOLS: FrontendTool[] = [
  {
    name: 'show_dynamic_form',
    description:
      'Render a form to collect structured input from the user; the submitted values are returned to you.',
    parameters: {
      type: 'object',
      properties: {
        title: { type: 'string', description: 'Form title' },
        description: { type: 'string', description: 'Optional form description shown under the title' },
        fields: {
          type: 'array',
          description: 'Form field definitions',
          items: {
            type: 'object',
            properties: {
              name: { type: 'string', description: 'Key under which the field value is returned' },
              label: { type: 'string', description: 'Human-readable field label' },
              type: {
                type: 'string',
                description: 'Input control to render for this field',
                enum: [
                  'text',
                  'password',
                  'url',
                  'email',
                  'number',
                  'textarea',
                  'select',
                  'toggle',
                  'checkbox-group',
                ],
              },
              required: { type: 'boolean', description: 'Whether the field must be filled in' },
              placeholder: { type: 'string', description: 'Placeholder hint text' },
              options: {
                type: 'array',
                description: 'Choices for select / checkbox-group fields',
                items: { type: 'string' },
              },
            },
            required: ['name', 'label', 'type'],
          },
        },
        submitLabel: { type: 'string', description: 'Submit button text' },
        cancelLabel: { type: 'string', description: 'Cancel button text' },
      },
      required: ['title', 'fields'],
    },
  },
  {
    name: 'show_data_table',
    description:
      'Present tabular data to the user with sorting, filtering, and pagination. '
      + 'If `selectable` is true, the rows the user chooses are returned to you.',
    parameters: {
      type: 'object',
      properties: {
        title: { type: 'string', description: 'Table title' },
        columns: {
          type: 'array',
          description: 'Column definitions in display order',
          items: {
            type: 'object',
            properties: {
              key: { type: 'string', description: 'Row property to read for this column' },
              label: { type: 'string', description: 'Column header label' },
              sortable: { type: 'boolean', description: 'Allow sorting by this column' },
              filterable: { type: 'boolean', description: 'Include this column in text filtering' },
              type: {
                type: 'string',
                description: 'Cell render style',
                enum: ['text', 'badge', 'date'],
              },
            },
            required: ['key', 'label'],
          },
        },
        rows: {
          type: 'array',
          description: 'Row objects keyed by the column keys',
          items: { type: 'object' },
        },
        selectable: { type: 'boolean', description: 'Allow the user to select rows and return them' },
        pageSize: { type: 'number', description: 'Rows per page' },
      },
      required: ['title', 'columns', 'rows'],
    },
  },
  {
    name: 'show_approval',
    description:
      'Ask the user to approve or reject an action; the boolean decision is returned to you.',
    parameters: {
      type: 'object',
      properties: {
        title: { type: 'string', description: 'Approval prompt title' },
        message: { type: 'string', description: 'The action or question the user is approving' },
        confirmLabel: { type: 'string', description: 'Approve button text' },
        cancelLabel: { type: 'string', description: 'Reject button text' },
        details: { type: 'string', description: 'Optional extra context shown below the message' },
      },
      required: ['title', 'message'],
    },
  },
]

/** Set of all frontend tool names for fast lookup. */
export const FRONTEND_TOOL_NAMES = new Set(FRONTEND_TOOLS.map((t) => t.name))

/** Map frontend tool names → canvas component activity types. */
export const FRONTEND_TOOL_COMPONENT_MAP: Record<string, string> = {
  show_dynamic_form: 'dynamic_form',
  show_data_table: 'data_table',
  show_approval: 'approval',
}

/**
 * Frontend tools whose canvas render is **terminal** — they don't ask the
 * user to act, so the chat client auto-resolves the deferred ToolMessage as
 * soon as the canvas opens. All three v1 tools are interactive (they wait for
 * the user to submit / cancel / decide before resolving), so this set is empty.
 */
export const DISPLAY_ONLY_FRONTEND_TOOLS = new Set<string>()
