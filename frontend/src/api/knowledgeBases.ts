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
  original_name: string
  mime_type: string
  status: 'pending' | 'processing' | 'indexed' | 'failed'
  page_count: number | null
  chunk_count: number | null
  error_message: string | null
  size_bytes?: number
  created_at: string
}

export interface KBCreate {
  name: string
  description?: string
  embedding_model?: string
}

export interface DocumentPreview {
  content: string | null
  filename: string
  mime_type: string
  truncated: boolean
  binary?: boolean
}

const API_BASE = import.meta.env.VITE_API_URL || ''

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
  previewDocument: (docId: string) =>
    api.get<DocumentPreview>(`/documents/${docId}/preview`).then(r => r.data),
  downloadDocumentUrl: (docId: string): string => {
    const token = localStorage.getItem('access_token') || ''
    return `${API_BASE}/api/v1/documents/${docId}/download?token=${token}`
  },
}
