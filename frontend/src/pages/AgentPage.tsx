/**
 * AI Agents page — create runs, view history, inspect execution trace.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { agentsApi, AgentRunDetail, AgentRunResponse, ToolCallResponse, ToolInfo } from '../api/agents'
import { useAuthStore } from '../stores/authStore'
import { useUIStore } from '../stores/uiStore'

// ------------------------------------------------------------------
// Risk badge
// ------------------------------------------------------------------
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

// ------------------------------------------------------------------
// Status badge for run
// ------------------------------------------------------------------
function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, string> = {
    pending:            'bg-neutral-100 text-neutral-600',
    running:            'bg-blue-100 text-blue-700',
    completed:          'bg-success-100 text-success-700',
    failed:             'bg-danger-100 text-danger-600',
    awaiting_approval:  'bg-yellow-100 text-yellow-700',
    cancelled:          'bg-neutral-200 text-neutral-500',
  }
  const dots: Record<string, string> = {
    running: '●', awaiting_approval: '⚠', completed: '✓', failed: '✗',
  }
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${cfg[status] || cfg.pending}`}>
      {dots[status] && <span aria-hidden="true">{dots[status]}</span>}
      {status.replace('_', ' ')}
    </span>
  )
}

// ------------------------------------------------------------------
// Tool call row
// ------------------------------------------------------------------
function ToolCallRow({ tc }: { tc: ToolCallResponse }) {
  const [expanded, setExpanded] = useState(false)
  const statusColor: Record<string, string> = {
    success: 'text-success-600', failed: 'text-danger-600',
    rejected: 'text-warning-700', timeout: 'text-danger-600',
  }

  return (
    <div className={`border-l-2 pl-4 py-2 ${tc.status === 'success' ? 'border-success-400' : tc.status === 'rejected' ? 'border-warning-400' : 'border-danger-400'}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`font-mono text-sm font-medium ${statusColor[tc.status] || 'text-neutral-600'}`}>
          {tc.status === 'success' ? '✓' : tc.status === 'rejected' ? '⊘' : '✗'} Step {tc.step_number}: {tc.tool_name}
        </span>
        {tc.sandbox_used && (
          <span className="text-xs bg-neutral-100 text-neutral-600 px-1.5 py-0.5 rounded font-mono">
            Sandboxed 🐳
          </span>
        )}
        {tc.duration_ms != null && (
          <span className="text-xs text-neutral-400">{tc.duration_ms}ms</span>
        )}
      </div>

      <button onClick={() => setExpanded(p => !p)}
        className="text-xs text-primary-600 mt-1 hover:underline">
        {expanded ? 'Hide details' : 'Show details'}
      </button>

      {expanded && (
        <div className="mt-2 space-y-2">
          <div>
            <p className="text-xs font-medium text-neutral-500 mb-0.5">Input</p>
            <pre className="text-xs bg-neutral-50 dark:bg-neutral-900 rounded p-2 overflow-x-auto">
              {JSON.stringify(tc.input_data, null, 2)}
            </pre>
          </div>
          {tc.output_data && (
            <div>
              <p className="text-xs font-medium text-neutral-500 mb-0.5">Output</p>
              <pre className="text-xs bg-neutral-50 dark:bg-neutral-900 rounded p-2 overflow-x-auto">
                {JSON.stringify(tc.output_data, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------
// New run form
// ------------------------------------------------------------------
function NewRunForm({ tools, onCreated }: { tools: ToolInfo[]; onCreated: (run: AgentRunResponse) => void }) {
  const [goal, setGoal] = useState('')
  const [maxIter, setMaxIter] = useState(10)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { addToast } = useUIStore()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!goal.trim()) return
    setLoading(true)
    setError('')
    try {
      const run = await agentsApi.createRun({ goal: goal.trim(), max_iterations: maxIter })
      addToast({ type: 'success', title: 'Agent run started', message: `Run ID: ${run.id.slice(0, 8)}` })
      onCreated(run)
      setGoal('')
    } catch (err: any) {
      setError(err?.response?.data?.error?.message || 'Failed to start agent run')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-white dark:bg-neutral-800 rounded-lg shadow-sm border border-neutral-200 dark:border-neutral-700 p-6">
      <h2 className="text-base font-semibold text-neutral-800 dark:text-neutral-100 mb-4">
        🤖 New Agent Run
      </h2>

      {/* Security notice */}
      <div className="mb-4 p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded text-xs text-blue-700 dark:text-blue-300">
        <strong>Security:</strong> All tool calls go through the Tool Registry → Policy check → Risk assessment → Human Approval (if High/Critical) → Controlled execution → Audit log.
        The LLM never executes anything directly.
      </div>

      {error && <div className="mb-4 p-3 bg-danger-50 border border-danger-200 rounded text-sm text-danger-700">{error}</div>}

      <form onSubmit={submit} className="space-y-4">
        <div>
          <label htmlFor="goal" className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Goal <span className="text-danger-500" aria-hidden="true">*</span>
          </label>
          <textarea
            id="goal" value={goal} onChange={e => setGoal(e.target.value)}
            rows={3} required maxLength={5000}
            placeholder="e.g. List the files in the workspace and calculate 2**10"
            className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 placeholder-neutral-400 focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        </div>

        <div>
          <label htmlFor="max-iter" className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
            Max Iterations (1–20)
          </label>
          <input
            id="max-iter" type="number" value={maxIter}
            onChange={e => setMaxIter(Math.min(20, Math.max(1, Number(e.target.value))))}
            min={1} max={20}
            className="w-24 rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        </div>

        <button type="submit" disabled={loading || !goal.trim()}
          className="px-6 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700 disabled:opacity-50 transition-colors">
          {loading ? 'Starting…' : 'Start Agent'}
        </button>
      </form>

      {/* Available tools */}
      {tools.length > 0 && (
        <div className="mt-6">
          <h3 className="text-xs font-semibold text-neutral-500 uppercase tracking-wider mb-2">Available Tools</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {tools.map(t => (
              <div key={t.name} className="flex items-start gap-2 p-2 bg-neutral-50 dark:bg-neutral-700/50 rounded text-xs">
                <div className="flex-1 min-w-0">
                  <span className="font-mono font-medium text-neutral-800 dark:text-neutral-100">{t.name}</span>
                  {t.requires_sandbox && <span className="ml-1 text-neutral-400">🐳</span>}
                </div>
                <RiskBadge level={t.risk_level} />
              </div>
            ))}
          </div>
          <p className="text-xs text-neutral-400 mt-2">🐳 = runs in Docker sandbox · High/Critical risk requires admin approval</p>
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------
// Run detail panel
// ------------------------------------------------------------------
function RunDetail({ runId, onBack }: { runId: string; onBack: () => void }) {
  const [run, setRun] = useState<AgentRunDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const { addToast } = useUIStore()

  useEffect(() => {
    let alive = true

    // Initial load
    agentsApi.getRun(runId).then(r => {
      if (alive) { setRun(r); setLoading(false) }
    }).catch(() => { if (alive) setLoading(false) })

    // SSE stream for live updates — uses fetch so we can send the Bearer token
    const { accessToken } = useAuthStore.getState()
    const sseAbort = new AbortController()

    const connectSSE = async () => {
      try {
        const resp = await fetch(`/api/v1/agents/runs/${runId}/stream`, {
          headers: { Authorization: `Bearer ${accessToken}` },
          signal: sseAbort.signal,
        })
        if (!resp.ok || !resp.body) return

        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let buf = ''

        while (alive) {
          const { done, value } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const lines = buf.split('\n')
          buf = lines.pop() ?? ''

          let shouldRefresh = false
          for (const line of lines) {
            if (line.startsWith('event:')) {
              shouldRefresh = true
            }
          }
          // Refresh the full run detail on any SSE event
          if (shouldRefresh && alive) {
            agentsApi.getRun(runId).then(r => {
              if (alive) setRun(r)
            }).catch(() => {})
          }
        }
      } catch {
        // AbortError = component unmounted. Other errors = stream closed. Both fine.
      }
    }

    connectSSE()

    return () => {
      alive = false
      sseAbort.abort()
    }
  }, [runId])

  const handleCancel = async () => {
    try {
      await agentsApi.cancelRun(runId)
      addToast({ type: 'info', title: 'Agent run cancelled' })
      const r = await agentsApi.getRun(runId)
      setRun(r)
    } catch { addToast({ type: 'error', title: 'Cancel failed' }) }
  }

  if (loading) return <div className="flex justify-center py-12"><div className="animate-spin h-8 w-8 border-2 border-primary-600 border-t-transparent rounded-full" /></div>
  if (!run) return <div className="text-neutral-400 text-center py-12">Run not found</div>

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <button onClick={onBack} className="text-xs text-primary-600 hover:underline mb-1">← Back to runs</button>
          <h2 className="text-lg font-semibold text-neutral-800 dark:text-neutral-100 line-clamp-2">{run.goal}</h2>
          <div className="flex items-center gap-3 mt-1 text-xs text-neutral-500">
            <StatusBadge status={run.status} />
            <span>Iteration {run.iteration_count}/{run.max_iterations}</span>
            <span>{run.step_count} steps</span>
          </div>
        </div>
        {['pending','running','awaiting_approval'].includes(run.status) && (
          <button onClick={handleCancel}
            className="flex-shrink-0 px-3 py-1.5 text-xs font-medium text-danger-600 border border-danger-300 rounded hover:bg-danger-50">
            Cancel
          </button>
        )}
      </div>

      {/* Awaiting approval banner */}
      {run.status === 'awaiting_approval' && (
        <div className="p-4 bg-warning-50 border border-warning-300 rounded-lg">
          <p className="text-sm font-semibold text-warning-800">⚠️ APPROVAL REQUIRED</p>
          <p className="text-xs text-warning-700 mt-1">
            The agent is paused. An administrator must approve or reject the pending action in the Approvals page.
          </p>
        </div>
      )}

      {/* Result */}
      {run.result && (
        <div className="p-4 bg-neutral-50 dark:bg-neutral-700 rounded-lg">
          <h3 className="text-xs font-semibold text-neutral-500 uppercase tracking-wider mb-2">Result</h3>
          <p className="text-sm text-neutral-800 dark:text-neutral-100 whitespace-pre-wrap">{run.result}</p>
        </div>
      )}
      {run.error_message && (
        <div className="p-3 bg-danger-50 border border-danger-200 rounded text-sm text-danger-700">
          {run.error_message}
        </div>
      )}

      {/* Execution trace */}
      <div className="bg-white dark:bg-neutral-800 rounded-lg shadow-sm border border-neutral-200 dark:border-neutral-700 p-5">
        <h3 className="text-base font-semibold text-neutral-800 dark:text-neutral-100 mb-4">Execution Trace</h3>
        {['pending','running'].includes(run.status) && (
          <div className="flex items-center gap-2 text-sm text-blue-600 mb-4">
            <span className="animate-spin h-4 w-4 border-2 border-blue-600 border-t-transparent rounded-full inline-block" aria-hidden="true" />
            Agent is running…
          </div>
        )}
        {run.tool_calls.length === 0 && !['pending','running'].includes(run.status) ? (
          <p className="text-sm text-neutral-400">No tool calls recorded.</p>
        ) : (
          <div className="space-y-3">
            {run.tool_calls.map(tc => <ToolCallRow key={tc.id} tc={tc} />)}
          </div>
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------
// Main page
// ------------------------------------------------------------------
export default function AgentPage() {
  const [runs, setRuns] = useState<AgentRunResponse[]>([])
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = async () => {
    const [r, t] = await Promise.all([
      agentsApi.listRuns().catch(() => []),
      agentsApi.listTools().catch(() => []),
    ])
    setRuns(r)
    setTools(t)
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const handleCreated = (run: AgentRunResponse) => {
    setRuns(prev => [run, ...prev])
    setSelectedRunId(run.id)
  }

  if (selectedRunId) {
    return (
      <RunDetail
        runId={selectedRunId}
        onBack={() => { setSelectedRunId(null); load() }}
      />
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">AI Agents</h1>
        <p className="text-sm text-neutral-500 mt-1">
          Goal-driven AI agents with controlled tool access, human approval gates, and full audit logging
        </p>
      </div>

      <NewRunForm tools={tools} onCreated={handleCreated} />

      {/* Run history */}
      <div className="bg-white dark:bg-neutral-800 rounded-lg shadow-sm border border-neutral-200 dark:border-neutral-700">
        <div className="px-6 py-4 border-b border-neutral-200 dark:border-neutral-700">
          <h2 className="text-base font-semibold text-neutral-800 dark:text-neutral-100">Run History</h2>
        </div>
        {loading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin h-6 w-6 border-2 border-primary-600 border-t-transparent rounded-full" />
          </div>
        ) : runs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <div className="text-3xl mb-2" aria-hidden="true">🤖</div>
            <p className="text-sm text-neutral-500">No agent runs yet</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-neutral-50 dark:bg-neutral-700 text-left">
                <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase">Goal</th>
                <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase">Status</th>
                <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase">Steps</th>
                <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase">Started</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-200 dark:divide-neutral-700">
              {runs.map(r => (
                <tr key={r.id}
                  onClick={() => setSelectedRunId(r.id)}
                  className="hover:bg-neutral-50 dark:hover:bg-neutral-700/50 cursor-pointer transition-colors">
                  <td className="px-4 py-3">
                    <span className="font-medium text-neutral-800 dark:text-neutral-100 line-clamp-1 block max-w-xs">
                      {r.goal}
                    </span>
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={r.status} /></td>
                  <td className="px-4 py-3 text-neutral-500">{r.step_count}</td>
                  <td className="px-4 py-3 text-xs text-neutral-400">
                    {new Date(r.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
