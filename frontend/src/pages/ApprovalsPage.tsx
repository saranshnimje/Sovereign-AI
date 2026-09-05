import { useEffect, useState } from 'react'
import { approvalsApi, ApprovalRequest } from '../api/approvals'
import { useUIStore } from '../stores/uiStore'
import Badge from '../components/ui/Badge'

const RISK_COLORS: Record<string, 'success' | 'warning' | 'danger' | 'info'> = {
  low: 'success', medium: 'warning', high: 'danger', critical: 'danger',
}
const STATUS_COLORS: Record<string, 'success' | 'warning' | 'danger' | 'info' | 'default'> = {
  approved: 'success', pending: 'warning', rejected: 'danger', expired: 'info',
}

export default function ApprovalsPage() {
  const { addToast } = useUIStore()
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState('pending')

  const load = async () => {
    setLoading(true)
    try {
      const data = await approvalsApi.list({ status: statusFilter || undefined })
      setApprovals(data.items); setTotal(data.total)
    } catch { /* ignore */ }
    setLoading(false)
  }
  useEffect(() => { load() }, [statusFilter])

  const handleApprove = async (approval: ApprovalRequest) => {
    try {
      const updated = await approvalsApi.approve(approval.id)
      setApprovals(prev => prev.map(a => a.id === updated.id ? updated : a))
      addToast({ type: 'success', title: 'Approved' })
    } catch { addToast({ type: 'error', title: 'Approve failed' }) }
  }

  const handleReject = async (approval: ApprovalRequest) => {
    const reason = window.prompt('Rejection reason (optional):')
    if (reason === null) return
    try {
      const updated = await approvalsApi.reject(approval.id, reason || undefined)
      setApprovals(prev => prev.map(a => a.id === updated.id ? updated : a))
      addToast({ type: 'info', title: 'Rejected' })
    } catch { addToast({ type: 'error', title: 'Reject failed' }) }
  }

  const timeAgo = (ts: string) => {
    const diff = Date.now() - new Date(ts).getTime()
    if (diff < 60000) return 'just now'
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`
    return `${Math.floor(diff / 86400000)}d ago`
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg md:text-2xl font-bold text-white">Approvals</h1>
        <p className="text-xs md:text-sm text-neutral-400 mt-1">Review and approve high-risk AI agent actions.</p>
      </div>

      <div className="flex gap-2 flex-wrap">
        {['pending', 'approved', 'rejected', 'expired', ''].map(s => (
          <button key={s} onClick={() => setStatusFilter(s)}
            className={`px-3 py-1.5 text-xs rounded-lg border transition-colors ${statusFilter === s ? 'bg-cyan-600 text-white border-cyan-600' : 'border-surface-border text-neutral-400 hover:bg-surface-muted'}`}>
            {s || 'All'}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="space-y-3">{[...Array(3)].map((_, i) => <div key={i} className="skeleton h-20" />)}</div>
      ) : approvals.length === 0 ? (
        <div className="bg-surface-raised border border-surface-border rounded-xl p-12 text-center">
          <div className="w-16 h-16 rounded-2xl bg-cyan-500/10 flex items-center justify-center text-3xl mx-auto mb-4">
            <svg className="w-8 h-8 text-cyan-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-white mb-2">No Approval Requests</h3>
          <p className="text-sm text-neutral-400">{statusFilter === 'pending' ? 'No pending approvals at this time.' : 'No approvals match this filter.'}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {approvals.map(approval => (
            <div key={approval.id} className="bg-surface-raised border border-surface-border rounded-xl p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="text-sm font-medium text-neutral-200">{approval.operation}</h3>
                    <Badge variant={RISK_COLORS[approval.risk_level] || 'default'} size="sm">{approval.risk_level} risk</Badge>
                    <Badge variant={STATUS_COLORS[approval.status] || 'default'} size="sm">{approval.status}</Badge>
                  </div>
                  <div className="flex gap-4 text-[11px] text-neutral-500">
                    <span>Run: {approval.agent_run_id.slice(0, 8)}</span>
                    <span>{timeAgo(approval.created_at)}</span>
                    {approval.expires_at && <span>Expires: {timeAgo(approval.expires_at)}</span>}
                  </div>
                </div>
                {approval.status === 'pending' && (
                  <div className="flex gap-2">
                    <button onClick={() => handleApprove(approval)}
                      className="px-3 py-1.5 text-xs bg-success-600 text-white rounded-lg hover:bg-success-500 font-medium">
                      Approve
                    </button>
                    <button onClick={() => handleReject(approval)}
                      className="px-3 py-1.5 text-xs border border-danger-500/50 text-danger-500 rounded-lg hover:bg-danger-500/10">
                      Reject
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
