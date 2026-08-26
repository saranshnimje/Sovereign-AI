import api from './client'

export interface ConversationResponse {
  id: string; title: string | null; model_name: string
  system_prompt: string | null; context_mode: string
  created_at: string; updated_at: string; message_count: number
}
export interface MessageResponse {
  id: string; role: string; content: string
  token_count: number | null; finish_reason: string | null
  created_at: string; metadata?: Record<string, unknown>
}
export interface ConversationDetail extends ConversationResponse {
  messages: MessageResponse[]
}

export const chatApi = {
  listConversations: (limit = 20, offset = 0) =>
    api.get<ConversationResponse[]>('/chat/conversations', { params: { limit, offset } }).then((r) => r.data),

  createConversation: (data: { model_name: string; title?: string; system_prompt?: string }) =>
    api.post<ConversationResponse>('/chat/conversations', data).then((r) => r.data),

  getConversation: (id: string) =>
    api.get<ConversationDetail>(`/chat/conversations/${id}`).then((r) => r.data),

  deleteConversation: (id: string) => api.delete(`/chat/conversations/${id}`),

  renameConversation: (id: string, title: string) =>
    api.patch<ConversationResponse>(`/chat/conversations/${id}`, { title }).then(r => r.data),

  exportConversation: (id: string, format: 'json' | 'markdown') =>
    api.get(`/chat/conversations/${id}/export`, {
      params: { format },
      responseType: 'blob',
    }).then((r) => r.data),
}
