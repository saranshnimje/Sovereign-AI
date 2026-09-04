import { useState } from 'react'
import type { TodoTask, SubAgentInfo } from '../../stores/chatStore'

interface AgentActivityProps {
  todo: TodoTask[]
  subagents: SubAgentInfo[]
  verificationStatus: 'none' | 'started' | 'passed' | 'failed'
  verificationType: string | null
  agentState: string | null
}

const TODO_STATUS_CONFIG: Record<string, { icon: string; color: string }> = {
  pending: { icon: '○', color: 'text-neutral-500' },
  active: { icon: '●', color: 'text-cyan-400 animate-pulse' },
  completed: { icon: '✓', color: 'text-emerald-400' },
  failed: { icon: '✕', color: 'text-red-400' },
  retried: { icon: '↻', color: 'text-amber-400' },
}

const AGENT_TYPE_ICONS: Record<string, string> = {
  researcher: '🔍',
  coder: '💻',
  tester: '🧪',
  reviewer: '📋',
  security: '🛡️',
  data_analyst: '📊',
}

const AGENT_STATE_LABELS: Record<string, { label: string; color: string; icon: string }> = {
  idle: { label: 'Idle', color: 'text-neutral-500', icon: '○' },
  planning: { label: 'Planning…', color: 'text-amber-400', icon: '📋' },
  reasoning: { label: 'Reasoning…', color: 'text-cyan-400', icon: '🧠' },
  executing: { label: 'Executing…', color: 'text-blue-400', icon: '⚙️' },
  verifying: { label: 'Verifying…', color: 'text-purple-400', icon: '🔍' },
  replanning: { label: 'Replanning…', color: 'text-amber-400', icon: '🔄' },
  observing: { label: 'Observing…', color: 'text-cyan-400', icon: '👁' },
  completed: { label: 'Completed', color: 'text-emerald-400', icon: '✓' },
  failed: { label: 'Failed', color: 'text-red-400', icon: '✕' },
  cancelled: { label: 'Cancelled', color: 'text-neutral-400', icon: '■' },
  retrying: { label: 'Retrying…', color: 'text-amber-400', icon: '↻' },
}

export default function AgentActivity({ todo, subagents, verificationStatus, verificationType, agentState }: AgentActivityProps) {
  const [expanded, setExpanded] = useState<'todo' | 'subagents' | null>('todo')

  // Show agent state indicator immediately, even before tasks/subagents appear
  const stateInfo = agentState ? AGENT_STATE_LABELS[agentState] : null
  const isActive = agentState && !['completed', 'failed', 'cancelled', 'idle'].includes(agentState)

  if (todo.length === 0 && subagents.length === 0 && verificationStatus === 'none' && !agentState) {
    return null
  }

  const completedCount = todo.filter(t => t.status === 'completed').length
  const failedCount = todo.filter(t => t.status === 'failed').length
  const activeCount = todo.filter(t => t.status === 'active').length

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50 overflow-hidden mb-3">
      {/* Agent State Indicator — always visible when agent is active */}
      {agentState && stateInfo && (
        <div className="px-3 py-2 text-xs border-b border-neutral-200 dark:border-neutral-700 flex items-center gap-2">
          <span className={`${stateInfo.color} ${isActive ? 'animate-pulse' : ''}`}>{stateInfo.icon}</span>
          <span className={`font-medium ${stateInfo.color}`}>{stateInfo.label}</span>
          {isActive && (
            <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse ml-1" />
          )}
        </div>
      )}

      {/* Todo List */}
      {todo.length > 0 && (
        <>
          <button
            onClick={() => setExpanded(expanded === 'todo' ? null : 'todo')}
            className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium
              text-neutral-600 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700/50 transition-colors"
          >
            <span className="flex items-center gap-2">
              <span>📋 Tasks ({todo.length})</span>
              {activeCount > 0 && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-300">
                  {activeCount} active
                </span>
              )}
              {completedCount > 0 && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
                  {completedCount} done
                </span>
              )}
              {failedCount > 0 && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300">
                  {failedCount} failed
                </span>
              )}
            </span>
            <span className="text-neutral-400">{expanded === 'todo' ? '▾' : '▸'}</span>
          </button>

          {expanded === 'todo' && (
            <div className="border-t border-neutral-200 dark:border-neutral-700 divide-y divide-neutral-100 dark:divide-neutral-700/50">
              {todo.map((task) => {
                const cfg = TODO_STATUS_CONFIG[task.status] || TODO_STATUS_CONFIG.pending
                return (
                  <div key={task.id} className="flex items-start gap-2 px-3 py-1.5 text-xs">
                    <span className={`mt-0.5 ${cfg.color}`}>{cfg.icon}</span>
                    <div className="flex-1 min-w-0">
                      <span className={`${
                        task.status === 'completed' ? 'text-neutral-500 line-through' :
                        task.status === 'failed' ? 'text-red-400' :
                        task.status === 'active' ? 'text-neutral-200' :
                        'text-neutral-400'
                      }`}>
                        {task.description}
                      </span>
                      {task.error && (
                        <div className="text-[10px] text-red-400/70 mt-0.5 truncate">
                          {task.error}
                        </div>
                      )}
                      {task.tool_name && (
                        <span className="text-[10px] text-neutral-500 ml-1">
                          ({task.tool_name})
                        </span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </>
      )}

      {/* Sub-agents */}
      {subagents.length > 0 && (
        <>
          <button
            onClick={() => setExpanded(expanded === 'subagents' ? null : 'subagents')}
            className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium
              text-neutral-600 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700/50 transition-colors
              border-t border-neutral-200 dark:border-neutral-700"
          >
            <span className="flex items-center gap-2">
              <span>🤖 Sub-agents ({subagents.length})</span>
              {subagents.filter(s => s.status === 'running').length > 0 && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-300 animate-pulse">
                  {subagents.filter(s => s.status === 'running').length} running
                </span>
              )}
            </span>
            <span className="text-neutral-400">{expanded === 'subagents' ? '▾' : '▸'}</span>
          </button>

          {expanded === 'subagents' && (
            <div className="border-t border-neutral-200 dark:border-neutral-700 divide-y divide-neutral-100 dark:divide-neutral-700/50">
              {subagents.map((agent) => (
                <div key={agent.session_id} className="flex items-center gap-2 px-3 py-1.5 text-xs">
                  <span>{AGENT_TYPE_ICONS[agent.agent_type] || '🤖'}</span>
                  <span className="text-neutral-400">{agent.agent_type}</span>
                  <span className="text-neutral-500 truncate flex-1">{agent.task}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                    agent.status === 'running' ? 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-300' :
                    agent.status === 'completed' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300' :
                    'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'
                  }`}>
                    {agent.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* Verification Status */}
      {verificationStatus !== 'none' && (
        <div className="border-t border-neutral-200 dark:border-neutral-700 px-3 py-2 text-xs">
          <span className="flex items-center gap-2">
            {verificationStatus === 'started' && (
              <>
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                <span className="text-amber-400">Verifying {verificationType}...</span>
              </>
            )}
            {verificationStatus === 'passed' && (
              <>
                <span className="text-emerald-400">✓</span>
                <span className="text-emerald-400">Verification passed ({verificationType})</span>
              </>
            )}
            {verificationStatus === 'failed' && (
              <>
                <span className="text-red-400">✕</span>
                <span className="text-red-400">Verification failed ({verificationType})</span>
              </>
            )}
          </span>
        </div>
      )}
    </div>
  )
}
