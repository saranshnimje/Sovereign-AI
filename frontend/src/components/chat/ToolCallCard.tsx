import { useState } from 'react'

export interface ToolCall {
  call_id: string
  tool: string
  status: 'pending' | 'running' | 'success' | 'error' | 'denied' | 'approval_required'
  input_summary?: string
  result_summary?: string
  error?: string
  duration_ms?: number
  reasoning?: string
  timestamp: number
}

interface ToolCallCardProps {
  calls: ToolCall[]
}

const STATUS_CONFIG: Record<string, { icon: string; color: string; label: string }> = {
  pending: { icon: '⏳', color: 'text-neutral-400', label: 'Pending' },
  running: { icon: '⏳', color: 'text-amber-500', label: 'Running' },
  success: { icon: '✓', color: 'text-emerald-600', label: 'Completed' },
  error: { icon: '✕', color: 'text-red-500', label: 'Failed' },
  denied: { icon: '⊘', color: 'text-neutral-400', label: 'Denied' },
  approval_required: { icon: '⚠', color: 'text-amber-500', label: 'Approval Required' },
}

const TOOL_ICONS: Record<string, string> = {
  calculator: '🔢',
  search_kb: '📚',
  knowledge_search: '📚',
  web_search: '🌐',
  web_fetch: '🌐',
  file_read: '📄',
  file_list: '📁',
  file_write: '✏️',
  file_delete: '🗑️',
  sensor_analysis: '📊',
  vision_inspection: '👁',
  incident_get: '📋',
  incident_investigate: '🔍',
  system_status: '⚙️',
  tool_discovery: '🔧',
  model_select: '🤖',
  time_now: '🕐',
  python_exec: '🐍',
  run_command: '💻',
  run_powershell: '⚡',
  spawn_subagent: '🤖',
  get_subagent_result: '📥',
  list_subagents: '📋',
  cancel_subagent: '🚫',
  search_org_data: '🏢',
}

function formatDuration(ms?: number): string {
  if (ms == null) return ''
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

export default function ToolCallCard({ calls }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState<string | null>(null)

  if (calls.length === 0) return null

  const runningCount = calls.filter(c => c.status === 'running').length
  const successCount = calls.filter(c => c.status === 'success').length
  const errorCount = calls.filter(c => c.status === 'error').length

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50 overflow-hidden mb-3">
      {/* Header */}
      <button
        onClick={() => setExpanded(expanded ? null : 'all')}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium
          text-neutral-600 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700/50 transition-colors"
      >
        <span className="flex items-center gap-2">
          <span>🔧 Tool calls ({calls.length})</span>
          {runningCount > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
              {runningCount} running
            </span>
          )}
          {successCount > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
              {successCount} ok
            </span>
          )}
          {errorCount > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300">
              {errorCount} failed
            </span>
          )}
        </span>
        <span className="text-neutral-400">{expanded ? '▾' : '▸'}</span>
      </button>

      {/* Tool call list */}
      <div className="border-t border-neutral-200 dark:border-neutral-700 divide-y divide-neutral-100 dark:divide-neutral-700/50">
        {calls.map((call) => {
          const cfg = STATUS_CONFIG[call.status] || STATUS_CONFIG.pending
          const icon = TOOL_ICONS[call.tool] || '🔧'
          const isExpanded = expanded === 'all' || expanded === call.call_id

          return (
            <div key={call.call_id}>
              {/* Compact row */}
              <button
                onClick={() => setExpanded(isExpanded ? null : call.call_id)}
                className="w-full flex items-center justify-between px-3 py-1.5 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-700/50 transition-colors"
              >
                <span className="flex items-center gap-2 min-w-0">
                  <span>{icon}</span>
                  <span className={`font-medium ${cfg.color}`}>{cfg.label}</span>
                  <span className="text-neutral-600 dark:text-neutral-300 truncate">
                    {call.tool}
                  </span>
                  {call.input_summary && (
                    <span className="text-neutral-400 truncate hidden sm:inline">
                      {call.input_summary}
                    </span>
                  )}
                </span>
                <span className="flex items-center gap-2 flex-shrink-0 ml-2">
                  {call.duration_ms != null && (
                    <span className="text-neutral-400 text-[10px]">
                      {formatDuration(call.duration_ms)}
                    </span>
                  )}
                  <span className={cfg.color}>{cfg.icon}</span>
                </span>
              </button>

              {/* Expanded details */}
              {isExpanded && (
                <div className="px-3 pb-2 pt-1 text-[11px] space-y-1 bg-neutral-100/50 dark:bg-neutral-700/30">
                  {call.input_summary && (
                    <div>
                      <span className="text-neutral-400">Input: </span>
                      <span className="text-neutral-600 dark:text-neutral-300">{call.input_summary}</span>
                    </div>
                  )}
                  {call.result_summary && (
                    <div>
                      <span className="text-neutral-400">Result: </span>
                      <span className="text-neutral-600 dark:text-neutral-300">{call.result_summary}</span>
                    </div>
                  )}
                  {call.error && (
                    <div>
                      <span className="text-red-500">Error: </span>
                      <span className="text-red-600 dark:text-red-400">{call.error}</span>
                    </div>
                  )}
                  {call.reasoning && (
                    <div>
                      <span className="text-neutral-400">Reasoning: </span>
                      <span className="text-neutral-500 dark:text-neutral-400 italic">{call.reasoning}</span>
                    </div>
                  )}
                  {call.duration_ms != null && (
                    <div>
                      <span className="text-neutral-400">Duration: </span>
                      <span className="text-neutral-600 dark:text-neutral-300">{formatDuration(call.duration_ms)}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
