import { useEffect, useMemo, useState } from 'react'
import type { AgentEvent } from '../../stores/chatStore'

interface AgentTimelineProps {
  events: AgentEvent[]
  isStreaming: boolean
}

const EVENT_CONFIG: Record<string, { icon: string; color: string; label: string }> = {
  agent_started: { icon: '🤖', color: 'text-cyan-400', label: 'Agent started' },
  understanding_started: { icon: '🧠', color: 'text-amber-400', label: 'Understanding request' },
  understanding_completed: { icon: '🧠', color: 'text-emerald-400', label: 'Intent classified' },
  plan_created: { icon: '📋', color: 'text-blue-400', label: 'Plan created' },
  plan_updated: { icon: '🔄', color: 'text-amber-400', label: 'Plan updated' },
  todo_updated: { icon: '📝', color: 'text-neutral-400', label: 'Tasks updated' },
  todo_task_added: { icon: '📝', color: 'text-neutral-400', label: 'Task added' },
  decision: { icon: '🧠', color: 'text-cyan-400', label: 'Agent decision' },
  retry: { icon: '↻', color: 'text-amber-400', label: 'Retrying' },
  tool_call: { icon: '🔧', color: 'text-blue-400', label: 'Tool call' },
  tool_started: { icon: '▶', color: 'text-blue-400', label: 'Tool started' },
  tool_result: { icon: '✓', color: 'text-emerald-400', label: 'Tool result' },
  tool_error: { icon: '✕', color: 'text-red-400', label: 'Tool error' },
  tool_timeout: { icon: '⏱', color: 'text-orange-400', label: 'Tool timed out' },
  observation: { icon: '👁', color: 'text-cyan-400', label: 'Observation' },
  verification: { icon: '🔍', color: 'text-purple-400', label: 'Verification' },
  verification_started: { icon: '🔍', color: 'text-purple-400', label: 'Verification started' },
  verification_passed: { icon: '✓', color: 'text-emerald-400', label: 'Verification passed' },
  verification_failed: { icon: '✕', color: 'text-red-400', label: 'Verification failed' },
  ask_user: { icon: '❓', color: 'text-cyan-400', label: 'Waiting for user' },
  subagent_spawned: { icon: '🤖', color: 'text-cyan-400', label: 'Sub-agent spawned' },
  subagent_completed: { icon: '🤖', color: 'text-emerald-400', label: 'Sub-agent completed' },
  final_response: { icon: '💬', color: 'text-emerald-400', label: 'Response ready' },
  done: { icon: '✓', color: 'text-emerald-400', label: 'Completed' },
  error: { icon: '✕', color: 'text-red-400', label: 'Error' },
  cancelled: { icon: '■', color: 'text-neutral-400', label: 'Cancelled' },
}

function formatTimestamp(isoStr: string | null): string {
  if (!isoStr) return ''
  try {
    return new Date(isoStr).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ''
  }
}

function text(value: unknown): string {
  if (value === undefined || value === null) return ''
  if (typeof value === 'string') return value
  try { return JSON.stringify(value) } catch { return String(value) }
}

function eventSummary(event: AgentEvent): string {
  const p = event.payload || {}
  const candidates = [p.tool, p.action, p.decision, p.activity, p.state, p.description, p.result_summary, p.reason, p.goal, p.message, p.question, p.content]
  const value = candidates.find(v => v !== undefined && v !== null && text(v).trim() !== '')
  return value === undefined ? '' : text(value).replace(/\s+/g, ' ').slice(0, 140)
}

function syntheticEvent(runId: string, sequence: number, event_type: string, payload: Record<string, unknown>, created_at: string | null): AgentEvent {
  return { id: `synthetic-${runId}-${sequence}-${event_type}`, run_id: runId, sequence, event_type, payload, created_at }
}

export default function AgentTimeline({ events, isStreaming }: AgentTimelineProps) {
  const [expanded, setExpanded] = useState(isStreaming)
  const [expandedEvents, setExpandedEvents] = useState<Set<string>>(new Set())

  const timelineEvents = useMemo(() => {
    const base = events.filter(e => !['token', 'agent_state'].includes(e.event_type)).sort((a, b) => a.sequence - b.sequence)
    const done = [...base].reverse().find(e => e.event_type === 'done')
    if (!done) return base

    // Completed runs may have only a compact agent_started/done pair in the
    // client store. Reconstruct useful execution steps from the rich `done`
    // payload so the user can still see what the agent actually did.
    const existingTypes = new Set(base.map(e => e.event_type))
    const additions: AgentEvent[] = []
    const payload = done.payload || {}
    const plan = Array.isArray(payload.plan) ? payload.plan : []
    const observations = Array.isArray(payload.observations) ? payload.observations : []
    const toolCalls = Number(payload.tool_calls || 0)

    if (plan.length > 0 && !existingTypes.has('plan_created')) {
      additions.push(syntheticEvent(done.run_id, Math.max(1, done.sequence - 3), 'plan_created', {
        steps: plan,
        synthesized: true,
      }, done.created_at))
    }

    if (toolCalls > 0 && !existingTypes.has('tool_call') && observations.length === 0) {
      additions.push(syntheticEvent(done.run_id, Math.max(1, done.sequence - 2), 'tool_call', {
        tool: `${toolCalls} tool call${toolCalls === 1 ? '' : 's'}`,
        synthesized: true,
      }, done.created_at))
    }

    observations.forEach((obs: any, index: number) => {
      const tool = obs?.tool || 'tool'
      const status = obs?.status || 'success'
      const facts = Array.isArray(obs?.facts) ? obs.facts : []
      const existingObservation = base.some(e => e.event_type === 'observation' && e.payload?.tool === tool)
      if (!existingObservation) {
        additions.push(syntheticEvent(done.run_id, Math.max(1, done.sequence - observations.length - 1 + index), 'observation', {
          tool,
          success: status === 'success',
          observation: facts.join('; ') || `${tool} completed with status ${status}`,
          synthesized: true,
        }, done.created_at))
      }
    })

    if (payload.verification && !existingTypes.has('verification')) {
      additions.push(syntheticEvent(done.run_id, Math.max(1, done.sequence - 1), 'verification', {
        ...payload.verification as Record<string, unknown>,
        synthesized: true,
      }, done.created_at))
    }

    return [...base, ...additions].sort((a, b) => a.sequence - b.sequence)
  }, [events])

  useEffect(() => {
    if (isStreaming) setExpanded(true)
  }, [isStreaming])

  if (timelineEvents.length === 0) return null

  const doneEvent = [...timelineEvents].reverse().find(e => e.event_type === 'done')
  const doneState = doneEvent?.payload?.state as string | undefined
  const hasError = timelineEvents.some(e => e.event_type === 'error' || e.event_type === 'tool_error')
  const isCancelled = timelineEvents.some(e => e.event_type === 'cancelled')
  const isComplete = doneState === 'completed'
  const isFailed = ['failed', 'timed_out'].includes(doneState || '') || hasError

  const toggleEvent = (id: string) => setExpandedEvents(prev => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id); else next.add(id)
    return next
  })

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50 overflow-hidden mb-3">
      <button onClick={() => setExpanded(v => !v)} className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-neutral-600 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700/50 transition-colors">
        <span className="flex items-center gap-2">
          <span>📊 Agent Timeline</span>
          <span className="text-[10px] text-neutral-500">({timelineEvents.length} events)</span>
          {isStreaming && <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />}
          {isComplete && <span className="text-emerald-400">✓</span>}
          {isFailed && <span className="text-red-400">✕</span>}
          {isCancelled && <span className="text-neutral-400">■</span>}
        </span>
        <span className="text-neutral-400">{expanded ? '▾' : '▸'}</span>
      </button>

      {expanded && (
        <div className="border-t border-neutral-200 dark:border-neutral-700 max-h-96 overflow-y-auto">
          {timelineEvents.map(event => {
            const cfg = EVENT_CONFIG[event.event_type] || { icon: '⚙️', color: 'text-neutral-500', label: event.event_type }
            const failedDone = event.event_type === 'done' && ['failed', 'timed_out'].includes(String(event.payload?.state || ''))
            const displayCfg = event.event_type === 'done'
              ? { ...cfg, icon: failedDone ? '✕' : event.payload?.state === 'cancelled' ? '■' : '✓', color: failedDone ? 'text-red-400' : event.payload?.state === 'cancelled' ? 'text-neutral-400' : 'text-emerald-400', label: failedDone ? (event.payload?.state === 'timed_out' ? 'Timed out' : 'Failed') : event.payload?.state === 'cancelled' ? 'Cancelled' : 'Completed' }
              : cfg
            const isEventExpanded = expandedEvents.has(event.id)
            const summary = eventSummary(event)
            return (
              <div key={event.id}>
                <button onClick={() => toggleEvent(event.id)} className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] hover:bg-neutral-100 dark:hover:bg-neutral-700/50 transition-colors text-left">
                  <span className={displayCfg.color}>{displayCfg.icon}</span>
                  <span className={`font-medium ${displayCfg.color}`}>{displayCfg.label}</span>
                  <span className="text-neutral-500 flex-1 truncate">{summary}</span>
                  <span className="text-neutral-500 text-[10px] flex-shrink-0">#{event.sequence}</span>
                  <span className="text-neutral-500 text-[10px] flex-shrink-0">{formatTimestamp(event.created_at)}</span>
                </button>
                {isEventExpanded && (
                  <div className="px-3 pb-2 pt-1 text-[10px] bg-neutral-100/50 dark:bg-neutral-700/30 mx-3 mb-1 rounded">
                    <pre className="text-neutral-500 dark:text-neutral-400 whitespace-pre-wrap break-words max-h-48 overflow-y-auto">{JSON.stringify(event.payload, null, 2)}</pre>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
