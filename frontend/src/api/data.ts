import api from './client'

export interface Organization {
  id: string
  name: string
  description: string | null
  industry: string | null
  location: string | null
  website: string | null
  founded: string | null
  employee_count: string | null
  revenue: string | null
  ceo: string | null
  phone: string | null
  email: string | null
  details: Record<string, unknown> | null
  owner_id: string
  kb_id: string | null
  created_at: string
}

export interface DataSource {
  id: string
  org_id: string
  type: string
  name: string
  config_json: Record<string, unknown> | null
  status: string
  doc_count: number
  created_at: string
}

export interface SensorAnalysis {
  id: string
  owner_id: string
  original_name: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  row_count: number | null
  result_json: Record<string, unknown> | null
  ai_explanation: string | null
  created_at: string
}

export const dataApi = {
  listOrgs: () => api.get<Organization[]>('/data/organizations').then(r => r.data),
  createOrg: (data: { name: string; description?: string; industry?: string; location?: string }) =>
    api.post<Organization>('/data/organizations', data).then(r => r.data),
  listDataSources: (orgId: string) =>
    api.get<DataSource[]>(`/data/organizations/${orgId}/sources`).then(r => r.data),
  listSensorAnalyses: () =>
    api.get<SensorAnalysis[]>('/data/sensor-analyses').then(r => r.data),
  uploadSensorData: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<SensorAnalysis>('/data/sensor-analyses', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
}
