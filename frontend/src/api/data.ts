import api from './client'

export interface Organization {
  id: string; name: string; description: string | null
  created_at: string; kb_id: string | null
  source_count: number; doc_count: number; chunk_count: number
  health: string
}

export interface DataSourceInfo {
  id: string; type: string; name: string; status: string
  config: Record<string, unknown>; note?: string | null; last_error?: string | null
}

export interface OrgDetail extends Organization {
  sources: DataSourceInfo[]
  documents: { id: string; name: string; status: string; chunks: number; size: number }[]
}

export const dataApi = {
  listOrgs: () => api.get<Organization[]>('/data/orgs').then(r => r.data),
  createOrg: (name: string, description?: string) =>
    api.post<Organization>('/data/orgs', { name, description }).then(r => r.data),
  getOrg: (id: string) => api.get<OrgDetail>(`/data/orgs/${id}`).then(r => r.data),
  deleteOrg: (id: string) => api.delete(`/data/orgs/${id}`),
  addSource: (orgId: string, type: string, name: string, config: object = {}) =>
    api.post<DataSourceInfo>(`/data/orgs/${orgId}/sources`,
      { type, name, config }).then(r => r.data),
  deleteSource: (orgId: string, srcId: string) =>
    api.delete(`/data/orgs/${orgId}/sources/${srcId}`),
  addDirect: (orgId: string, title: string, content: string, tags?: string[]) =>
    api.post(`/data/orgs/${orgId}/direct`, { title, content, tags },
      { timeout: 120000 }).then(r => r.data),
  addWeb: (orgId: string, url: string, name?: string) =>
    api.post(`/data/orgs/${orgId}/web`, { url, name },
      { timeout: 120000 }).then(r => r.data),
  testDb: (orgId: string, cfg: object) =>
    api.post(`/data/orgs/${orgId}/db/test`, { type: 'database', name: 't', config: cfg },
      { timeout: 30000 }).then(r => r.data),
  dbSchema: (orgId: string, sourceId: string) =>
    api.get<{ tables: Record<string, number> }>(
      `/data/orgs/${orgId}/db/schema?source_id=${sourceId}`).then(r => r.data),
  dbSync: (orgId: string, sourceId: string, tables: string[]) =>
    api.post<{ synced: Record<string, string> }>(`/data/orgs/${orgId}/db/sync`,
      { source_id: sourceId, tables }, { timeout: 180000 }).then(r => r.data),
}
