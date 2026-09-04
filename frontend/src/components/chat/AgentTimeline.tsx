import { useMemo, useState } from 'react'
import type { AgentEvent } from '../../stores/chatStore'

interface AgentTimelineProps {
  events: AgentEvent[]
  isStreaming: boolean
}

const EVENT_CONFIG: Record<string, { icon: string; color: string; label: string }> = {
  agent_started: { icon: '🤖', color: 'text-cyan-400', label: 'Agent started' },
  understanding_started: { icon: '🧠', color: 'text-amber-400', label: 'Understanding…' },
  understanding_completed: { icon: '🧠', color: 'text-emerald-400', label: 'Intent classified' },
  plan_created: { icon: '📋', color: 'text-blue-400', label: 'Plan created' },
  plan_updated: { icon: '🔄', color: 'text-amber-400', label: 'Plan updated' },
  todo_updated: { icon: '📝', color: 'text-neutral-400', label: 'Tasks updated' },
  decision: { icon: '🧠', color: 'text-cyan-400', label: 'Reasoning' },
  tool_call: { icon: '🔧', color: 'text-blue-400', label: 'Tool call' },
  tool_result: { icon: '🔧', color: 'text-neutral-400', label: 'Tool result' },
  tool_error: { icon: '✕', color: 'text-red-400', label: 'Tool error' },
  tool_timeout: { icon: '⏱', color: 'text-orange-400', label: 'Tool timed out' },
  observation: { icon: '👁', color: 'text-cyan-400', label: 'Observation' },
  verification_started: { icon: '🔍', color: 'text-purple-400', label: 'Verifying…' },
  verification_passed: { icon: '✓', color: 'text-emerald-400', label: 'Verification passed' },
  verification_failed: { icon: '✕', color: 'text-red-400', label: 'Verification failed' },
  retry: { icon: '↻', color: 'text-amber-400', label: 'Retrying' },
  final_response: { icon: '💬', color: 'text-emerald-400', label: 'Response ready' },
  done: { icon: '✓', color: 'text-emerald-400', label: 'Completed' },
  error: { icon: '✕', color: 'text-red-400', label: 'Error' },
  cancelled: { icon: '■', color: 'text-neutral-400', label: 'Cancelled' },
  agent_state: { icon: '⚙️', color: 'text-neutral-500', label: 'State' },
  token: { icon: '💬', color: 'text-neutral-500', label: 'Token' },
  subagent_spawned: { icon: '🤖', color: 'text-cyan-400', label: 'Sub-agent spawned' },
  subagent_completed: { icon: '🤖', color: 'text-emerald-400', label: 'Sub-agent done' },
}

function formatTimestamp(isoStr: string | null): string {
  if (!isoStr) return ''
  try {
    const d = new Date(isoStr)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ''
  }
}

export default function AgentTimeline({ events, isStreaming }: AgentTimelineProps) {
  const [expanded, setExpanded] = useState(false)
  const [expandedEvents, setExpandedEvents] = useState<Set<string>>(new Set())

  // Filter out noise events (token, agent_state updates) for cleaner timeline
  const timelineEvents = useMemo(() => {
    return events.filter(e =>
      !['token', 'agent_state'].includes(e.event_type)
    )
  }, [events])

  if (timelineEvents.length === 0) return null

  const toggleEvent = (id: string) => {
    setExpandedEvents(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // Get the final status from done/error/cancelled events
  const lastEvent = timelineEvents[timelineEvents.length - 1]
  const isComplete = lastEvent?.event_type === 'done'
  const isError = lastEvent?.event_type === 'error'
  const isCancelled = lastEvent?.event_type === 'cancelled'

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50 overflow-hidden mb-3">
      {/* Header */}
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium
          text-neutral-600 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700/50 transition-colors"
      >
        <span className="flex items-center gap-2">
          <span>📊 Agent Timeline</span>
          <span className="text-[10px] text-neutral-500">({timelineEvents.length} events)</span>
          {isStreaming && (
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
          )}
          {isComplete && <span className="text-emerald-400">✓</span>}
          {isError && <span className="text-red-400">✕</span>}
          {isCancelled && <span className="text-neutral-400">■</span>}
        </span>
        <span className="text-neutral-400">{expanded ? '▾' : '▸'}</span>
      </button>

      {/* Timeline */}
      {expanded && (
        <div className="border-t border-neutral-200 dark:border-neutral-700 max-h-80 overflow-y-auto">
          {timelineEvents.map((event) => {
            const cfg = EVENT_CONFIG[event.event_type] || {
              icon: '⚙️', color: 'text-neutral-500', label: event.event_type,
            }
            const isExpanded = expandedEvents.has(event.id)

            return (
              <div key={event.id}>
                <button
                  onClick={() => toggleEvent(event.id)}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] hover:bg-neutral-100 dark:hover:bg-neutral-700/50 transition-colors text-left"
                >
                  <span className={cfg.color}>{cfg.icon}</span>
                  <span className={`font-medium ${cfg.color}`}>{cfg.label}</span>
                  <span className="text-neutral-500 flex-1 truncate">
                    {event.payload?.goal
                      ? String(event.payload.goal).slice(0, 60)
                      : event.payload?.reason
                        ? String(event.payload.reason).slice(0, 60)
                        : event.payload?.tool
                          ? String(event.payload.tool)
                          : event.payload?.content
                            ? String(event.payload.content).slice(0, 60)
                            : event.payload?.message
                              ? String(event.payload.message).slice(0, 60)
                              : ''}
                  </span>
                  <span className="text-neutral-500 text-[10px] flex-shrink-0">
                    #{event.sequence}
                  </span>
                  <span className="text-neutral-500 text-[10px] flex-shrink-0">
                    {formatTimestamp(event.created_at)}
                  </span>
                </button>

                {/* Expanded payload */}
                {isExpanded && (
                  <div className="px-3 pb-2 pt-1 text-[10px] bg-neutral-100/50 dark:bg-neutral-700/30 mx-3 mb-1 rounded">
                    <pre className="text-neutral-500 dark:text-neutral-400 whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
                      {JSON.stringify(event.payload, null, 2)}
                    </pre>
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
