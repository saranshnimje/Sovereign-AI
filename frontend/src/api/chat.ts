import api from './client'

export interface ConversationResponse {
  id: string; title: string | null; model_name: string
  system_prompt: string | null; context_mode: string
  created_at: string; updated_at: string; message_count: number
}

export interface CitationSource {
  index: number
  source_type: string
  label: string
  doc_id?: string
  filename?: string
  page_number?: number | null
  score?: number
  content_preview?: string
  analysis_id?: string
  sensor?: string
  severity?: string
}

export interface MessageResponse {
  id: string; role: string; content: string
  token_count: number | null; finish_reason: string | null
  created_at: string; run_id?: string | null; metadata?: {
    local?: boolean
    model?: string
    agent?: { activity?: { tool: string; status: string; ms?: number }[] }
    evidence?: { sources: CitationSource[]; source_count: number }
    run_id?: string
  }
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

  getAgentEvents: (convId: string) =>
    api.get<{ events: AgentEventRecord[]; runs: AgentRunRecord[] }>(
      `/chat/conversations/${convId}/agent-events`
    ).then((r) => r.data),
}

export interface AgentEventRecord {
  id: string
  run_id: string
  sequence: number
  event_type: string
  payload: Record<string, unknown>
  created_at: string | null
}

export interface AgentRunRecord {
  id: string
  goal: string
  status: string
  result: string | null
  step_count: number
  model_name: string | null
  created_at: string | null
}
