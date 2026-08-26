import api from './client'

export interface SystemSettings {
  default_chunk_size: number
  default_chunk_overlap: number
  default_top_k: number
  default_score_threshold: number
  default_max_iterations: number
  approval_timeout_minutes: number
  sandbox_timeout_s: number
  sandbox_mem_limit_mb: number
  sandbox_cpu_quota: number
  max_upload_size_mb: number
}

export interface DashboardSummary {
  knowledge_base_count: number
  document_count: number
  agent_run_count: number
  pending_approval_count: number
  total_audit_events: number
}

export interface ActivityItem {
  id: string
  sequence_num: number
  timestamp: string
  event_type: string
  action: string
  outcome: string
  resource_type: string | null
  resource_id: string | null
  user_id: string | null
}

export interface AuditLogItem {
  id: string
  sequence_num: number
  timestamp: string
  user_id: string | null
  event_type: string
  action: string
  resource_type: string | null
  resource_id: string | null
  outcome: string
  ip_address: string | null
  metadata: Record<string, unknown> | null
}

export interface UserItem {
  id: string
  email: string
  username: string
  role: string
  is_active: boolean
  last_login: string | null
  created_at: string
}

export const settingsApi = {
  get: () => api.get<SystemSettings>('/settings/').then(r => r.data),
  update: (data: SystemSettings) => api.put<SystemSettings>('/settings/', data).then(r => r.data),
  summary: () => api.get<DashboardSummary>('/settings/summary').then(r => r.data),
  users: () => api.get<UserItem[]>('/settings/users').then(r => r.data),
}

export const auditApi = {
  list: (params?: {
    event_type?: string; user_id?: string; outcome?: string; ip_address?: string
    start_date?: string; end_date?: string; limit?: number; offset?: number
  }) => api.get<{ items: AuditLogItem[]; total: number }>('/audit/logs', { params }).then(r => r.data),

  verify: () => api.get<{
    verified: boolean; entries_checked: number
    first_error_at_sequence: number | null; message: string
  }>('/audit/verify').then(r => r.data),

  exportUrl: (format: 'csv' | 'json', filters?: { event_type?: string; outcome?: string }) => {
    const params = new URLSearchParams({ format, ...(filters || {}) })
    return `/api/v1/audit/export?${params}`
  },
}

export const activityApi = {
  recent: (limit = 10) =>
    api.get<{ items: ActivityItem[] }>(`/system/activity?limit=${limit}`).then(r => r.data),
}

export const approvalBadgeApi = {
  count: () => api.get<{ count: number }>('/approvals/count').then(r => r.data).catch(() => ({ count: 0 })),
}
