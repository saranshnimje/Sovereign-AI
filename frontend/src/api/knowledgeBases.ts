import api from './client'

export interface KnowledgeBase {
  id: string
  name: string
  description: string | null
  embedding_model: string
  qdrant_collection: string
  doc_count: number
  chunk_count: number
  owner_id: string
  created_at: string
  updated_at: string
}

export interface Document {
  id: string
  kb_id: string
  filename: string
  mime_type: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  page_count: number | null
  chunk_count: number | null
  error_message: string | null
  created_at: string
}

export interface KBCreate {
  name: string
  description?: string
  embedding_model?: string
}

export const knowledgeBasesApi = {
  list: () => api.get<KnowledgeBase[]>('/knowledge-bases/').then(r => r.data),
  get: (id: string) => api.get<KnowledgeBase>(`/knowledge-bases/${id}`).then(r => r.data),
  create: (data: KBCreate) => api.post<KnowledgeBase>('/knowledge-bases/', data).then(r => r.data),
  delete: (id: string) => api.delete(`/knowledge-bases/${id}`),
  listDocuments: (kbId: string) => api.get<Document[]>(`/knowledge-bases/${kbId}/documents`).then(r => r.data),
  uploadDocument: (kbId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<Document>(`/knowledge-bases/${kbId}/documents`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
  deleteDocument: (kbId: string, docId: string) => api.delete(`/knowledge-bases/${kbId}/documents/${docId}`),
}
