import api from './client'

export interface ProcessingStep {
  step: string
  status: string
  duration_ms: number | null
  detail?: string
}

export interface DocumentResponse {
  id: string
  kb_id: string
  original_name: string
  mime_type: string
  size_bytes: number
  status: string      // pending | processing | indexed | failed
  page_count: number | null
  chunk_count: number
  error_message: string | null
  created_at: string
  updated_at: string
  processing_steps?: ProcessingStep[]
}

export interface KBResponse {
  id: string
  name: string
  description: string | null
  embedding_model: string
  qdrant_collection: string
  doc_count: number
  chunk_count: number
  created_at: string
  updated_at: string
}

export interface KBQuerySource {
  chunk_id: string
  doc_id: string
  filename: string
  page_number: number | null
  content: string
  score: number
}

export interface KBQueryResponse {
  answer: string | null
  sources: KBQuerySource[]
  query_embedding_ms: number
  retrieval_ms: number
  generation_ms: number | null
  low_confidence: boolean
  error: string | null
}

export const documentsApi = {
  upload: (formData: FormData) =>
    api.post<DocumentResponse>('/documents/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then((r) => r.data),

  list: (kbId?: string) =>
    api.get<DocumentResponse[]>('/documents/', { params: kbId ? { kb_id: kbId } : {} })
      .then((r) => r.data),

  get: (id: string) =>
    api.get<DocumentResponse>(`/documents/${id}`).then((r) => r.data),

  delete: (id: string) => api.delete(`/documents/${id}`),
}

export const kbApi = {
  create: (data: { name: string; description?: string; embedding_model?: string }) =>
    api.post<KBResponse>('/knowledge-bases/', data).then((r) => r.data),

  list: () => api.get<KBResponse[]>('/knowledge-bases/').then((r) => r.data),

  get: (id: string) => api.get<KBResponse>(`/knowledge-bases/${id}`).then((r) => r.data),

  delete: (id: string) => api.delete(`/knowledge-bases/${id}`),

  query: (
    id: string,
    payload: { query: string; top_k?: number; generate_answer?: boolean; model_name?: string }
  ) =>
    api.post<KBQueryResponse>(`/knowledge-bases/${id}/query`, payload).then((r) => r.data),
}
