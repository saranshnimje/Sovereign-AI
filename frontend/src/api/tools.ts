import api from './client'

export interface Tool {
  name: string
  description: string
  risk_level: string
  category: string
  required_role: string
  enabled: boolean
  config: Record<string, unknown> | null
}

export interface Plugin {
  id: string
  name: string
  description: string
  enabled: boolean
  config: Record<string, unknown> | null
}

export const toolsApi = {
  listTools: () => api.get<Tool[]>('/tools/').then(r => r.data),
  setToolEnabled: (name: string, enabled: boolean) =>
    api.patch<Tool>(`/tools/${name}`, { enabled }).then(r => r.data),
  setToolConfig: (name: string, config: Record<string, unknown>) =>
    api.put<Tool>(`/tools/${name}/config`, config).then(r => r.data),
  listPlugins: () => api.get<Plugin[]>('/tools/plugins').then(r => r.data),
  setPluginEnabled: (id: string, enabled: boolean) =>
    api.patch<Plugin>(`/tools/plugins/${id}`, { enabled }).then(r => r.data),
}
