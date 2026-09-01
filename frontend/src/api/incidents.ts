import api from './client'

export interface Incident {
  id: string
  title: string
  owner_id: string
  machine: string | null
  kb_id: string | null
  sensor_analysis_id: string | null
  evidence_json: string | null
  risk_json: string | null
  ai_analysis: string | null
  recommendation_action: string | null
  status: 'open' | 'investigating' | 'resolved' | 'closed'
  created_at: string
  updated_at: string
}

export const incidentsApi = {
  list: (params?: { status?: string; limit?: number; offset?: number }) =>
    api.get<{ items: Incident[]; total: number }>('/incidents/', { params }).then(r => r.data),
  get: (id: string) => api.get<Incident>(`/incidents/${id}`).then(r => r.data),
  create: (data: { title: string; machine?: string }) =>
    api.post<Incident>('/incidents/', data).then(r => r.data),
  update: (id: string, data: Partial<Incident>) =>
    api.patch<Incident>(`/incidents/${id}`, data).then(r => r.data),
  investigate: (id: string) =>
    api.post<Incident>(`/incidents/${id}/investigate`).then(r => r.data),
}
