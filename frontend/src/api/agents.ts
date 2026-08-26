import api from './client'

export interface ToolCallResponse {
  id: string
  step_number: number
  tool_name: string
  input_data: Record<string, unknown>
  output_data: Record<string, unknown> | null
  status: string          // success | failed | timeout | rejected
  exit_code: number | null
  duration_ms: number | null
  sandbox_used: boolean
  container_id: string | null
  created_at: string
}

export interface AgentRunResponse {
  id: string
  goal: string
  status: string          // pending | running | completed | failed | awaiting_approval | cancelled
  step_count: number
  iteration_count: number
  result: string | null
  error_message: string | null
  model_name: string | null
  max_iterations: number
  created_at: string
  updated_at: string
}

export interface AgentRunDetail extends AgentRunResponse {
  tool_calls: ToolCallResponse[]
}

export interface ToolInfo {
  name: string
  description: string
  risk_level: string
  requires_sandbox: boolean
  required_role: string
  tags: string[]
}

export interface ApprovalResponse {
  id: string
  agent_run_id: string | null
  requester_id: string
  operation: string
  operation_detail: { tool: string; input: Record<string, unknown> }
  risk_level: string
  status: string
  decided_by: string | null
  decided_at: string | null
  decision_note: string | null
  expires_at: string
  created_at: string
}

export const agentsApi = {
  createRun: (data: {
    goal: string
    model_name?: string
    allowed_tools?: string[]
    kb_ids?: string[]
    max_iterations?: number
  }) => api.post<AgentRunResponse>('/agents/runs', data).then(r => r.data),

  listRuns: (limit = 20, offset = 0) =>
    api.get<AgentRunResponse[]>('/agents/runs', { params: { limit, offset } })
       .then(r => r.data),

  getRun: (id: string) =>
    api.get<AgentRunDetail>(`/agents/runs/${id}`).then(r => r.data),

  cancelRun: (id: string) =>
    api.post<AgentRunResponse>(`/agents/runs/${id}/cancel`).then(r => r.data),

  listTools: () =>
    api.get<ToolInfo[]>('/agents/tools').then(r => r.data),
}

export const approvalsApi = {
  listPending: () =>
    api.get<ApprovalResponse[]>('/approvals/pending').then(r => r.data),

  get: (id: string) =>
    api.get<ApprovalResponse>(`/approvals/${id}`).then(r => r.data),

  approve: (id: string, note?: string) =>
    api.post<ApprovalResponse>(`/approvals/${id}/approve`, { note }).then(r => r.data),

  reject: (id: string, note: string) =>
    api.post<ApprovalResponse>(`/approvals/${id}/reject`, { note }).then(r => r.data),
}
