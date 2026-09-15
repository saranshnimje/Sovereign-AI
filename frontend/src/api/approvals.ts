import api from './client'

export interface ApprovalRequest {
  id: string
  agent_run_id: string
  requester_id: string
  operation: string
  operation_detail?: Record<string, unknown>
  risk_level: 'low' | 'medium' | 'high' | 'critical'
  status: 'pending' | 'approved' | 'rejected' | 'expired'
  decided_by: string | null
  decided_at?: string | null
  decision_note?: string | null
  expires_at: string | null
  created_at: string
}

export const approvalsApi = {
  list: (params?: { status?: string; limit?: number; offset?: number }) =>
    api.get<{ items: ApprovalRequest[]; total: number }>('/approvals/', { params }).then(r => r.data),
  approve: (id: string, note?: string) =>
    api.post<ApprovalRequest>(`/approvals/${id}/approve`, { note }).then(r => r.data),
  reject: (id: string, note?: string) =>
    api.post<ApprovalRequest>(`/approvals/${id}/reject`, { note }).then(r => r.data),
  count: () => api.get<{ count: number }>('/approvals/count').then(r => r.data).catch(() => ({ count: 0 })),
}
