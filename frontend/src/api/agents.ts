import api from './client'

export interface AgentRun {
  id: string
  user_id: string
  goal: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  plan_json: string | null
  result: string | null
  step_count: number
  iteration_count: number
  model_name: string | null
  created_at: string
  updated_at: string
}

export interface ToolCallRecord {
  id: string
  agent_run_id: string
  step_number: number
  tool_name: string
  input_json: string | null
  output_json: string | null
  status: 'pending' | 'running' | 'success' | 'error' | 'denied'
  exit_code: number | null
  duration_ms: number | null
  sandbox_used: boolean
  created_at: string
}

export const agentsApi = {
  listRuns: (params?: { status?: string; limit?: number; offset?: number }) =>
    api.get<{ items: AgentRun[]; total: number }>('/agents/runs', { params }).then(r => r.data),
  getRun: (id: string) => api.get<AgentRun>(`/agents/runs/${id}`).then(r => r.data),
  getToolCalls: (runId: string) => api.get<ToolCallRecord[]>(`/agents/runs/${runId}/tool-calls`).then(r => r.data),
  cancelRun: (id: string) => api.post(`/agents/runs/${id}/cancel`).then(r => r.data),
  answerQuestion: (runId: string, answer: string) =>
    api.post(`/agents/runs/${runId}/answer`, { answer }).then(r => r.data),
}
