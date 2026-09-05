import { useEffect, useState } from 'react'
import { agentsApi, AgentRun, ToolCallRecord } from '../api/agents'
import { useUIStore } from '../stores/uiStore'
import Badge from '../components/ui/Badge'

const STATUS_COLORS: Record<string, 'success' | 'warning' | 'danger' | 'info' | 'default'> = {
  completed: 'success', running: 'warning', failed: 'danger', pending: 'info', cancelled: 'default',
}

export default function AgentsPage() {
  const { addToast } = useUIStore()
  const [runs, setRuns] = useState<AgentRun[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [selectedRun, setSelectedRun] = useState<AgentRun | null>(null)
  const [toolCalls, setToolCalls] = useState<ToolCallRecord[]>([])
  const [loadingTools, setLoadingTools] = useState(false)
  const [statusFilter, setStatusFilter] = useState('')
  const [offset, setOffset] = useState(0)
  const limit = 20

  const load = async () => {
    setLoading(true)
    try {
      const data = await agentsApi.listRuns({ status: statusFilter || undefined, limit, offset })
      setRuns(data.items); setTotal(data.total)
    } catch { /* ignore */ }
    setLoading(false)
  }
  useEffect(() => { load() }, [statusFilter, offset])

  const loadToolCalls = async (run: AgentRun) => {
    setSelectedRun(run)
    setLoadingTools(true)
    try { const tc = await agentsApi.getToolCalls(run.id); setToolCalls(tc) }
    catch { setToolCalls([]) }
    setLoadingTools(false)
  }

  const handleCancel = async (run: AgentRun) => {
    try {
      await agentsApi.cancelRun(run.id)
      setRuns(prev => prev.map(r => r.id === run.id ? { ...r, status: 'cancelled' as const } : r))
      addToast({ type: 'info', title: 'Run cancelled' })
    } catch { addToast({ type: 'error', title: 'Cancel failed' }) }
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
        <h1 className="text-lg md:text-2xl font-bold text-white">Agents</h1>
        <p className="text-xs md:text-sm text-neutral-400 mt-1">Monitor AI agent runs, tool calls, and execution flows.</p>
      </div>

      <div className="flex gap-2 md:gap-3 items-center flex-wrap">
        {['', 'running', 'completed', 'failed', 'pending', 'cancelled'].map(s => (
          <button key={s} onClick={() => { setStatusFilter(s); setOffset(0) }}
            className={`px-2 md:px-3 py-1.5 text-xs rounded-lg border transition-colors ${statusFilter === s ? 'bg-cyan-600 text-white border-cyan-600' : 'border-surface-border text-neutral-400 hover:bg-surface-muted'}`}>
            {s || 'All'}
          </button>
        ))}
        <span className="ml-auto text-xs text-neutral-500">{total} runs</span>
      </div>

      {loading ? (
        <div className="space-y-3">{[...Array(5)].map((_, i) => <div key={i} className="skeleton h-20" />)}</div>
      ) : runs.length === 0 ? (
        <div className="bg-surface-raised border border-surface-border rounded-xl p-12 text-center">
          <div className="w-16 h-16 rounded-2xl bg-cyan-500/10 flex items-center justify-center text-3xl mx-auto mb-4">
            <svg className="w-8 h-8 text-cyan-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-white mb-2">No Agent Runs</h3>
          <p className="text-sm text-neutral-400">Agent runs will appear here when you use agent mode in chat.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {runs.map(run => (
            <div key={run.id} className="bg-surface-raised border border-surface-border rounded-xl p-4 hover:border-cyan-700/50 transition-all cursor-pointer"
              onClick={() => loadToolCalls(run)}>
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="text-sm font-medium text-neutral-200 truncate">{run.goal}</h3>
                    <Badge variant={STATUS_COLORS[run.status] || 'default'} size="sm">{run.status}</Badge>
                  </div>
                  <div className="flex gap-4 text-[11px] text-neutral-500">
                    <span>{run.step_count} steps</span>
                    <span>{run.iteration_count} iterations</span>
                    {run.model_name && <span>{run.model_name}</span>}
                    <span>{timeAgo(run.created_at)}</span>
                  </div>
                </div>
                {run.status === 'running' && (
                  <button onClick={(e) => { e.stopPropagation(); handleCancel(run) }}
                    className="text-xs px-2 py-1 border border-danger-500/50 text-danger-500 rounded-lg hover:bg-danger-500/10">
                    Cancel
                  </button>
                )}
              </div>
              {run.result && (
                <p className="text-xs text-neutral-400 mt-2 truncate">{run.result}</p>
              )}
            </div>
          ))}
        </div>
      )}

      {total > limit && (
        <div className="flex justify-center gap-2">
          <button onClick={() => setOffset(Math.max(0, offset - limit))} disabled={offset === 0}
            className="px-3 py-1.5 border border-surface-border text-neutral-400 rounded-lg text-xs hover:bg-surface-muted disabled:opacity-40">
            Previous
          </button>
          <span className="px-3 py-1.5 text-xs text-neutral-500">
            {Math.floor(offset / limit) + 1} / {Math.ceil(total / limit)}
          </span>
          <button onClick={() => setOffset(offset + limit)} disabled={offset + limit >= total}
            className="px-3 py-1.5 border border-surface-border text-neutral-400 rounded-lg text-xs hover:bg-surface-muted disabled:opacity-40">
            Next
          </button>
        </div>
      )}

      {selectedRun && (
        <div className="bg-surface-raised border border-surface-border rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-white">Tool Calls - {selectedRun.goal}</h2>
            <button onClick={() => setSelectedRun(null)} className="text-xs text-neutral-500 hover:text-neutral-300">Close</button>
          </div>
          {loadingTools ? (
            <div className="flex justify-center py-8"><div className="animate-spin h-6 w-6 border-2 border-cyan-500 border-t-transparent rounded-full" /></div>
          ) : toolCalls.length === 0 ? (
            <p className="text-sm text-neutral-500 text-center py-8">No tool calls recorded.</p>
          ) : (
            <div className="space-y-2">
              {toolCalls.map(tc => (
                <div key={tc.id} className="p-3 bg-surface-overlay rounded-lg border border-surface-border">
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-mono text-cyan-400">{tc.tool_name}</span>
                      <Badge variant={STATUS_COLORS[tc.status] || 'default'} size="sm">{tc.status}</Badge>
                    </div>
                    {tc.duration_ms != null && <span className="text-[10px] text-neutral-500">{tc.duration_ms}ms</span>}
                  </div>
                  {tc.output_json && (
                    <pre className="text-[10px] text-neutral-400 mt-1 bg-surface rounded p-2 overflow-x-auto max-h-24 overflow-y-auto">
                      {tc.output_json.slice(0, 500)}
                    </pre>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
