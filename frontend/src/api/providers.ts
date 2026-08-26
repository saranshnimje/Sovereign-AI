import api from './client'

export type ProviderType =
  | 'ollama' | 'openai' | 'anthropic' | 'gemini'
  | 'openai_compatible' | 'openrouter' | 'opencode_zen' | 'nvidia'
export type ProviderEnvironment = 'local' | 'cloud' | 'custom'

export interface ProviderResponse {
  id: string
  name: string
  provider_type: ProviderType
  environment: ProviderEnvironment
  base_url: string | null
  /** Legacy pinned model — "" when the provider relies on auto-discovery */
  model_name: string
  has_api_key: boolean       // true = key stored; key itself is NEVER returned
  /** Masked hint, e.g. "••••••••abcd" — at most the last 4 characters */
  api_key_masked: string | null
  enabled: boolean
  supports_streaming: boolean
  supports_embeddings: boolean
  description: string | null
  /** Selectable (available + enabled) discovered models */
  model_count: number
  created_at: string
  updated_at: string
}

/** Provider preset shown in the Add-Provider picker */
export interface ProviderPreset {
  id: string
  label: string
  description: string
  provider_type: ProviderType
  environment: ProviderEnvironment
  default_base_url: string
  requires_api_key: boolean
  api_key_hint: string | null
  api_key_url: string | null
  supports_discovery: boolean
  adapter: string
}

/** A persisted discovered model belonging to a provider */
export interface ModelRecord {
  id: string                 // record id (used for enable/disable)
  provider_id: string
  model_id: string           // provider-native name, e.g. "llama3.2:3b"
  display_name: string | null
  family: string | null
  parameter_size: string | null
  quantization: string | null
  size_bytes: number | null
  modified_at: string | null
  context_length: number | null
  status: 'available' | 'unavailable'
  enabled: boolean
}

export interface ProviderCreate {
  name: string
  provider_type: ProviderType
  environment?: ProviderEnvironment
  base_url?: string
  /** Optional legacy field — providers no longer require a manually typed model */
  model_name?: string
  api_key?: string            // write-only
  enabled?: boolean
  supports_streaming?: boolean
  supports_embeddings?: boolean
  description?: string
}

export interface ProviderUpdate {
  name?: string
  environment?: ProviderEnvironment
  base_url?: string
  model_name?: string
  api_key?: string            // write-only; null = don't change
  enabled?: boolean
  supports_streaming?: boolean
  supports_embeddings?: boolean
  description?: string
}

export interface ProviderTestResult {
  success: boolean
  latency_ms: number | null
  provider: string
  model: string
  error: string | null
  /** Number of models discovered from the provider during the test (if listing succeeded) */
  models_found: number | null
}

/** A model available from a connected provider — only fields the provider returns are set */
export interface DiscoveredModel {
  name: string
  display_name: string
  family: string | null
  parameter_size: string | null
  quantization: string | null
  size_bytes: number | null
  modified_at: string | null
  context_length: number | null
  vision_capable: boolean | null
  embedding_capable: boolean | null
  status: string
}

export const PROVIDER_LABELS: Record<ProviderType, string> = {
  ollama: 'Ollama',
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  gemini: 'Google Gemini',
  openai_compatible: 'OpenAI-Compatible',
  openrouter: 'OpenRouter',
  opencode_zen: 'OpenCode Zen',
  nvidia: 'NVIDIA NIM',
}

export const ENV_LABELS: Record<ProviderEnvironment, string> = {
  local: '🖥 Local',
  cloud: '☁️ Cloud',
  custom: '⚙️ Custom',
}

export const providersApi = {
  list: () => api.get<ProviderResponse[]>('/models/providers/').then(r => r.data),
  get: (id: string) => api.get<ProviderResponse>(`/models/providers/${id}`).then(r => r.data),
  presets: () => api.get<ProviderPreset[]>('/models/providers/presets').then(r => r.data),
  create: (data: ProviderCreate) =>
    api.post<ProviderResponse>('/models/providers/', data).then(r => r.data),
  update: (id: string, data: ProviderUpdate) =>
    api.put<ProviderResponse>(`/models/providers/${id}`, data).then(r => r.data),
  delete: (id: string) => api.delete(`/models/providers/${id}`),
  test: (id: string) =>
    api.post<ProviderTestResult>(`/models/providers/${id}/test`).then(r => r.data),
  /** Live discovery + upsert of the persisted catalog */
  refreshModels: (id: string) =>
    api.post<ModelRecord[]>(`/models/providers/${id}/refresh`).then(r => r.data),
  /** Persisted catalog — no live call */
  getModels: (id: string) =>
    api.get<ModelRecord[]>(`/models/providers/${id}/models`).then(r => r.data),
  setModelEnabled: (providerId: string, recordId: string, enabled: boolean) =>
    api.patch<ModelRecord>(`/models/providers/${providerId}/models/${recordId}`,
      { enabled }).then(r => r.data),
}

/** Per-user preferred chat model */
export interface ModelPreference {
  provider_id: string | null
  model_name: string | null
}

export const prefsApi = {
  get: () => api.get<ModelPreference>('/models/preferences').then(r => r.data),
  set: (provider_id: string | null, model_name: string) =>
    api.put<ModelPreference>('/models/preferences',
      { provider_id, model_name }).then(r => r.data),
}
