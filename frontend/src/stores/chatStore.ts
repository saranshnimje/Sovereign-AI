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
}))
