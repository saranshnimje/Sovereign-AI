/**
 * Admin Approvals page — review and decide on pending high-risk agent actions.
 * Security: only admins can reach this page; only admins can approve/reject.
 */
import { useEffect, useState } from 'react'
import { approvalsApi, ApprovalResponse } from '../api/agents'
import { useUIStore } from '../stores/uiStore'

function RiskBadge({ level }: { level: string }) {
  const cfg: Record<string, string> = {
    low:      'bg-green-100 text-green-700',
    medium:   'bg-yellow-100 text-yellow-700',
    high:     'bg-orange-100 text-orange-700',
    critical: 'bg-red-100 text-red-700 font-semibold',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${cfg[level] || cfg.medium}`}>
      {level.toUpperCase()}
    </span>
  )
}

function ApprovalCard({ req, onDecision }: {
  req: ApprovalResponse
  onDecision: (id: string, decision: 'approved' | 'rejected') => void
}) {
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const { addToast } = useUIStore()

  const isExpired = new Date(req.expires_at) <= new Date()
  const expiresIn = Math.max(0, Math.round((new Date(req.expires_at).getTime() - Date.now()) / 1000))

  const decide = async (approved: boolean) => {
    if (!approved && !note.trim()) {
      addToast({ type: 'warning', title: 'Note required', message: 'Please provide a reason for rejection' })
      return
    }
    setSubmitting(true)
    try {
      if (approved) {
        await approvalsApi.approve(req.id, note || undefined)
        addToast({ type: 'success', title: 'Approved', message: req.operation })
        onDecision(req.id, 'approved')
      } else {
        await approvalsApi.reject(req.id, note)
        addToast({ type: 'info', title: 'Rejected', message: req.operation })
        onDecision(req.id, 'rejected')
      }
    } catch (err: any) {
      addToast({ type: 'error', title: 'Decision failed', message: err?.response?.data?.error?.message })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={`bg-white dark:bg-neutral-800 rounded-lg shadow-sm border p-6 ${req.risk_level === 'critical' ? 'border-red-300' : 'border-orange-300'}`}>
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-lg" aria-hidden="true">⚠️</span>
            <h3 className="text-base font-semibold text-neutral-800 dark:text-neutral-100">
              APPROVAL REQUIRED
            </h3>
            <RiskBadge level={req.risk_level} />
          </div>
          <p className="text-sm text-neutral-600 dark:text-neutral-400">{req.operation}</p>
        </div>
        {!isExpired && (
          <span className="text-xs text-warning-600 bg-warning-50 border border-warning-200 rounded px-2 py-1 flex-shrink-0">
            Expires in {expiresIn}s
          </span>
        )}
        {isExpired && (
          <span className="text-xs text-neutral-400 bg-neutral-100 rounded px-2 py-1 flex-shrink-0">Expired</span>
        )}
      </div>

      {/* Operation detail */}
      <div className="space-y-3 mb-5">
        <div className="bg-neutral-50 dark:bg-neutral-700 rounded p-3">
          <p className="text-xs font-semibold text-neutral-500 uppercase mb-2">Requested Operation</p>
          <div className="space-y-1 text-sm">
            <div className="flex gap-2">
              <span className="text-neutral-500 w-20 flex-shrink-0">Tool:</span>
              <code className="font-mono text-neutral-800 dark:text-neutral-100">
                {req.operation_detail?.tool || '—'}
              </code>
            </div>
            {req.operation_detail?.input && (
              <div>
                <span className="text-neutral-500 text-xs block mb-1">Input:</span>
                <pre className="text-xs bg-neutral-100 dark:bg-neutral-600 rounded p-2 overflow-x-auto">
                  {JSON.stringify(req.operation_detail.input, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </div>

        <div className="text-xs text-neutral-500 space-y-1">
          <p>Requested: <span className="text-neutral-700 dark:text-neutral-300">{new Date(req.created_at).toLocaleString()}</span></p>
          {req.agent_run_id && (
            <p>Run ID: <code className="font-mono text-neutral-700 dark:text-neutral-300">{req.agent_run_id.slice(0, 8)}…</code></p>
          )}
        </div>

        {/* Risk assessment */}
        {req.risk_level === 'high' && (
          <div className="bg-orange-50 border border-orange-200 rounded p-3 text-xs text-orange-800">
            <strong>High Risk:</strong> This operation may be difficult to reverse. Review carefully before approving.
          </div>
        )}
        {req.risk_level === 'critical' && (
          <div className="bg-red-50 border border-red-200 rounded p-3 text-xs text-red-800">
            <strong>Critical Risk:</strong> This operation could have significant consequences. Only approve if you are certain it is safe and intentional.
          </div>
        )}
      </div>

      {/* Decision note */}
      <div className="mb-4">
        <label htmlFor={`note-${req.id}`} className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
          Decision note <span className="text-neutral-400 font-normal">(required for rejection)</span>
        </label>
        <textarea
          id={`note-${req.id}`}
          value={note} onChange={e => setNote(e.target.value)}
          rows={2} placeholder="Add a note…"
          disabled={isExpired || submitting}
          className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50"
        />
      </div>

      <div className="flex justify-end gap-3">
        <button onClick={() => decide(false)}
          disabled={isExpired || submitting}
          className="px-4 py-2 text-sm font-medium text-danger-600 border border-danger-300 rounded-md hover:bg-danger-50 disabled:opacity-50 transition-colors">
          Reject
        </button>
        <button onClick={() => decide(true)}
          disabled={isExpired || submitting}
          className="px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-md hover:bg-primary-700 disabled:opacity-50 transition-colors">
          {submitting ? 'Processing…' : 'Approve'}
        </button>
      </div>
    </div>
  )
}

export default function ApprovalsPage() {
  const [pending, setPending] = useState<ApprovalResponse[]>([])
  const [loading, setLoading] = useState(true)

  const load = async () => {
    const reqs = await approvalsApi.listPending().catch(() => [])
    setPending(reqs)
    setLoading(false)
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 10_000) // poll every 10s
    return () => clearInterval(id)
  }, [])

  const handleDecision = (reqId: string, decision: 'approved' | 'rejected') => {
    setPending(prev => prev.filter(r => r.id !== reqId))
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">
            Approvals
            {pending.length > 0 && (
              <span className="ml-2 bg-danger-600 text-white text-xs px-2 py-0.5 rounded-full">{pending.length}</span>
            )}
          </h1>
          <p className="text-sm text-neutral-500 mt-1">
            Review and approve or reject high-risk agent actions
          </p>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin h-8 w-8 border-2 border-primary-600 border-t-transparent rounded-full" />
        </div>
      ) : pending.length === 0 ? (
        <div className="flex flex-col items-center justify-center min-h-64 text-center">
          <div className="text-4xl mb-3" aria-hidden="true">✅</div>
          <p className="text-neutral-600 dark:text-neutral-400 font-medium">No pending approvals</p>
          <p className="text-sm text-neutral-400 mt-1">New requests will appear here automatically</p>
        </div>
      ) : (
        <div className="space-y-4">
          {pending.map(req => (
            <ApprovalCard key={req.id} req={req} onDecision={handleDecision} />
          ))}
        </div>
      )}
    </div>
  )
}
