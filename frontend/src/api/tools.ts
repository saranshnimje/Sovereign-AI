import api from './client'

export interface ToolInfo {
  name: string
  description: string
  category: string
  version: string
  risk_level: 'low' | 'medium' | 'high' | 'critical'
  required_role: string
  permissions: string[]
  tags: string[]
  enabled: boolean
  available: boolean
  requires_sandbox: boolean
  config: Record<string, unknown>
  config_keys: string[]
  provided_by: string | null
  input_schema: Record<string, unknown>
}

export interface PluginInfo {
  id: string
  name: string
  version: string
  description: string
  author: string
  tools: string[]
  tools_detail: { name: string; enabled: boolean }[]
  permissions: string[]
  enabled: boolean
}

export const toolsApi = {
  list: () => api.get<ToolInfo[]>('/tools').then(r => r.data),
  enable: (name: string) => api.post(`/tools/${name}/enable`).then(r => r.data),
  disable: (name: string) => api.post(`/tools/${name}/disable`).then(r => r.data),
  test: (name: string) =>
    api.post<{ success: boolean; latency_ms?: number; note?: string; error?: string }>(
      `/tools/${name}/test`).then(r => r.data),
}

export const pluginsApi = {
  list: () => api.get<PluginInfo[]>('/plugins').then(r => r.data),
  enable: (id: string) => api.post(`/plugins/${id}/enable`).then(r => r.data),
  disable: (id: string) => api.post(`/plugins/${id}/disable`).then(r => r.data),
  test: (id: string) =>
    api.post<{ success: boolean; enabled: boolean; note: string | null }>(
      `/plugins/${id}/test`).then(r => r.data),
}
