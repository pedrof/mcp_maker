// TypeScript types mirroring the backend Pydantic schemas.
// Keep in sync with backend/app/schemas/models.py and backend/app/schemas/assist.py.

export type ModelStatus = 'draft' | 'published' | 'unpublished'
export type Visibility = 'public' | 'protected'
export type ToolClass = 'schema_only' | 'crud' | 'scenario'

export interface Model {
  id: string
  name: string
  description: string | null
  json_schema: Record<string, unknown>
  system_prompt: string | null
  enabled_tool_classes: ToolClass[]
  metrics_config: Record<string, unknown>
  visibility: Visibility
  status: ModelStatus
  current_version: number
  owner_sub: string
  created_at: string
  updated_at: string
}

export interface ModelVersion {
  id: string
  model_id: string
  version_number: number
  json_schema: Record<string, unknown>
  system_prompt: string | null
  enabled_tool_classes: ToolClass[]
  metrics_config: Record<string, unknown>
  created_at: string
}

export interface PublishResponse {
  model_id: string
  version: number
  status: ModelStatus
  mcp_endpoint: string
}

export interface ModelCreate {
  id?: string
  name: string
  description?: string
  json_schema?: Record<string, unknown>
  system_prompt?: string
  enabled_tool_classes?: ToolClass[]
  metrics_config?: Record<string, unknown>
  visibility?: Visibility
}

export interface ModelUpdate {
  name?: string
  description?: string
  json_schema?: Record<string, unknown>
  system_prompt?: string
  enabled_tool_classes?: ToolClass[]
  metrics_config?: Record<string, unknown>
  visibility?: Visibility
}

export interface AssistRequest {
  model_id: string
  intent: string
  prior_draft?: string
  feedback?: string
}

export interface AssistResponse {
  model_id: string
  system_prompt: string
  rationale: string
}

export interface SessionMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface TestSessionRequest {
  model_id: string
  messages: SessionMessage[]
}

export interface TestSessionResponse {
  model_id: string
  response: string
  tool_calls_made: number
  messages: unknown[]
}
