// Thin fetch wrapper. Uses Vite proxy in dev; configure VITE_API_BASE in production.
import type {
  AssistRequest, AssistResponse, Model, ModelCreate, ModelUpdate,
  ModelVersion, PublishResponse, TestSessionRequest, TestSessionResponse,
} from './types'

const BASE = import.meta.env.VITE_API_BASE ?? ''

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`${method} ${path} → ${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

// ── Models ────────────────────────────────────────────────────────────────────

export const api = {
  models: {
    list: () => request<Model[]>('GET', '/api/models'),
    get: (id: string) => request<Model>('GET', `/api/models/${id}`),
    create: (body: ModelCreate) => request<Model>('POST', '/api/models', body),
    update: (id: string, body: ModelUpdate) =>
      request<Model>('PATCH', `/api/models/${id}`, body),
    publish: (id: string) =>
      request<PublishResponse>('POST', `/api/models/${id}/publish`),
    unpublish: (id: string) =>
      request<Model>('POST', `/api/models/${id}/unpublish`),
    versions: (id: string) =>
      request<ModelVersion[]>('GET', `/api/models/${id}/versions`),
  },

  assist: {
    systemPrompt: (body: AssistRequest) =>
      request<AssistResponse>('POST', '/api/assist/system-prompt', body),
  },

  testSession: (body: TestSessionRequest) =>
    request<TestSessionResponse>('POST', '/api/test/session', body),
}
