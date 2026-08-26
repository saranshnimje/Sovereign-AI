import api from './client'

export interface ServiceStatus { status: string; latency_ms?: number; detail?: string }
export interface ResourceMetrics {
  cpu_percent: number; ram_used_gb: number; ram_total_gb: number
  disk_used_gb: number; disk_total_gb: number; gpu_available: boolean
}
export interface SystemStatus {
  status: string
  services: Record<string, ServiceStatus>
  resources: ResourceMetrics
  models_loaded: string[]
}
export interface ModelInfo {
  name: string; display_name: string; family?: string
  parameter_size?: string; quantization?: string
  size_bytes?: number; roles: string[]; status: string
  modified_at?: string
}

export const systemApi = {
  health: () => api.get<{ status: string }>('/system/health').then((r) => r.data),
  status: () => api.get<SystemStatus>('/system/status').then((r) => r.data),
  resources: () => api.get<ResourceMetrics>('/system/resources').then((r) => r.data),
  listModels: () => api.get<ModelInfo[]>('/models/').then((r) => r.data),
  getRoles: () => api.get<Record<string, string | null>>('/models/roles').then((r) => r.data),
  setRole: (role: string, model_name: string, provider_id?: string | null) =>
    api.put('/models/roles', { role, model_name, provider_id: provider_id ?? null }).then((r) => r.data),
  modelHealth: (name: string) =>
    api.get(`/models/health/${encodeURIComponent(name)}`).then((r) => r.data),
}
