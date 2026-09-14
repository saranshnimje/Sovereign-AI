import { create } from 'zustand'
import type { ConversationDetail, ConversationResponse, CitationSource } from '../api/chat'
import type { ToolCall } from '../components/chat/ToolCallCard'

export interface TodoTask {
  id: number
  description: string
  status: 'pending' | 'active' | 'completed' | 'failed' | 'retried'
  tool_name?: string
  subagent_type?: string
  error?: string
  retry_count?: number
}

export interface SubAgentInfo {
  session_id: string
  agent_type: string
  task: string
  status: string
}

export interface AgentEvent {
  id: string
  run_id: string
  sequence: number
  event_type: string
  payload: Record<string, unknown>
  created_at: string | null
}

export interface ActiveStream {
  convId: string
  streaming: boolean
  streamContent: string
  streamSources: CitationSource[]
  toolCalls: ToolCall[]
  lastError: string | null
  abortController: AbortController | null
  startedAt: number
  runId: string // Unique ID for this stream run, used to filter stale events
  // Agent state
  todo: TodoTask[]
  subagents: SubAgentInfo[]
  agentState: string | null
  verificationStatus: 'none' | 'started' | 'passed' | 'failed'
  verificationType: string | null
  // ASK_USER: pending question state
  askUser: {
    question: string
    options: string[]
    runId: string
  } | null
}

interface ChatState {
  conversations: ConversationResponse[]
  setConversations: (conversations: ConversationResponse[]) => void
  updateConversation: (id: string, updates: Partial<ConversationResponse>) => void
  addConversation: (conv: ConversationResponse) => void
  removeConversation: (id: string) => void

  activeStreams: Record<string, ActiveStream>
  startStream: (convId: string) => ActiveStream
  updateStream: (convId: string, updates: Partial<Omit<ActiveStream, 'convId'>>) => void
  endStream: (convId: string) => void
  getStream: (convId: string) => ActiveStream | undefined

  // Durable agent events per conversation — persists after streaming ends
  agentEvents: Record<string, AgentEvent[]>
  addAgentEvent: (convId: string, event: AgentEvent) => void
  setAgentEvents: (convId: string, events: AgentEvent[]) => void
  clearAgentEvents: (convId: string) => void
}

export const useChatStore = create<ChatState>((set, get) => ({
  conversations: [],
  setConversations: (conversations) => set({ conversations }),
  updateConversation: (id, updates) =>
    set((s) => ({
      conversations: s.conversations.map((c) =>
        c.id === id ? { ...c, ...updates } : c
      ),
    })),
  addConversation: (conv) =>
    set((s) => ({
      conversations: [conv, ...s.conversations.filter((c) => c.id !== conv.id)],
    })),
  removeConversation: (id) =>
    set((s) => ({
      conversations: s.conversations.filter((c) => c.id !== id),
    })),

  activeStreams: {},
  startStream: (convId) => {
    const existing = get().activeStreams[convId]
    if (existing) return existing
    const stream: ActiveStream = {
      convId,
      streaming: true,
      streamContent: '',
      streamSources: [],
      toolCalls: [],
      lastError: null,
      abortController: null,
      startedAt: Date.now(),
      runId: `run-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
      todo: [],
      subagents: [],
      agentState: null,
      verificationStatus: 'none',
      verificationType: null,
      askUser: null,
    }
    set((s) => ({
      activeStreams: { ...s.activeStreams, [convId]: stream },
    }))
    return stream
  },
  updateStream: (convId, updates) =>
    set((s) => {
      const existing = s.activeStreams[convId]
      if (!existing) return s
      return {
        activeStreams: {
          ...s.activeStreams,
          [convId]: { ...existing, ...updates },
        },
      }
    }),
  endStream: (convId) =>
    set((s) => {
      const { [convId]: _, ...rest } = s.activeStreams
      return { activeStreams: rest }
    }),
  getStream: (convId) => get().activeStreams[convId],

  // Durable agent events — survives streaming end and browser refresh
  agentEvents: {},
  addAgentEvent: (convId, event) =>
    set((s) => {
      const existing = s.agentEvents[convId] || []
      // TASK 4: Deduplicate by (run_id, sequence) not by id.
      // Live events use id="evt-{runId}-{seq}", persisted events use DB UUIDs.
      // Using (run_id, sequence) ensures they collapse correctly.
      if (existing.some(e => e.run_id === event.run_id && e.sequence === event.sequence)) return s
      return {
        agentEvents: {
          ...s.agentEvents,
          [convId]: [...existing, event].sort((a, b) => a.sequence - b.sequence),
        },
      }
    }),
  setAgentEvents: (convId, events) =>
    set((s) => {
      // TASK 4: Merge persisted events with existing live events instead of
      // replacing. Live events (from SSE) may have different ids than persisted
      // events (from DB), so we merge by (run_id, sequence) key.
      const existing = s.agentEvents[convId] || []
      if (existing.length === 0) {
        return {
          agentEvents: {
            ...s.agentEvents,
            [convId]: events.sort((a, b) => a.sequence - b.sequence),
          },
        }
      }
      // Build a map of existing events keyed by (run_id, sequence)
      const merged = new Map<string, typeof events[0]>()
      for (const e of existing) {
        merged.set(`${e.run_id}::${e.sequence}`, e)
      }
      // Persisted events fill gaps but don't overwrite live events
      for (const e of events) {
        const key = `${e.run_id}::${e.sequence}`
        if (!merged.has(key)) {
          merged.set(key, e)
        }
      }
      return {
        agentEvents: {
          ...s.agentEvents,
          [convId]: Array.from(merged.values()).sort((a, b) => a.sequence - b.sequence),
        },
      }
    }),
  clearAgentEvents: (convId) =>
    set((s) => {
      const { [convId]: _, ...rest } = s.agentEvents
      return { agentEvents: rest }
    }),
}))
