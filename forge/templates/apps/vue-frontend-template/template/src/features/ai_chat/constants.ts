/**
 * Centralized constants for the AI chat feature.
 */

export const MODEL_OPTIONS = [
  { value: 'openai:gpt-4.1', label: 'GPT-4.1' },
  { value: 'openai:gpt-4.1-mini', label: 'GPT-4.1 Mini' },
  { value: 'anthropic:claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
] as const

export const ENGINE_TYPES = {
  AG_UI: 'ag-ui',
  MCP_EXT: 'mcp-ext',
} as const

export const ACTIVITY_TYPES = {
  // Canvas components
  DYNAMIC_FORM: 'dynamic_form',
  DATA_TABLE: 'data_table',
  REPORT: 'report',
  WORKFLOW: 'workflow',
  CODE_VIEWER: 'code_viewer',
  FALLBACK: 'fallback',

  // Workspace components
  CREDENTIAL_FORM: 'credential_form',
  FILE_EXPLORER: 'file_explorer',
  APPROVAL_REVIEW: 'approval_review',
  USER_PROMPT: 'user_prompt',
} as const

export const ACTION_TYPES = {
  HITL_RESPONSE: 'hitl_response',
  FORM_SUBMIT: 'form_submit',
  FORM_CANCEL: 'form_cancel',
  MCP_TOOL_CALL: 'mcp_tool_call',
  MCP_MESSAGE: 'mcp_message',
  TOOL_APPROVAL: 'tool_approval',
  SUBMIT_CREDENTIALS: 'submit_credentials',
  WORKFLOW_ACTION: 'workflow_action',
} as const
