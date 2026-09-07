import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { parseServerDate, istDateParts } from '../utils/dates'
import { chatApi, ConversationDetail, ConversationResponse, CitationSource } from '../api/chat'
import { providersApi, prefsApi, ModelRecord, ProviderResponse } from '../api/providers'
import { API_BASE } from '../api/client'
import { useAuthStore } from '../stores/authStore'
import { useUIStore } from '../stores/uiStore'
import { useChatStore } from '../stores/chatStore'
import MessageBubble from '../components/chat/MessageBubble'
import StreamingBubble from '../components/chat/StreamingBubble'
import EvidencePanel from '../components/chat/EvidencePanel'
import ToolCallCard, { ToolCall } from '../components/chat/ToolCallCard'
import AgentActivity from '../components/chat/AgentActivity'
import AgentTimeline from '../components/chat/AgentTimeline'

interface ChatModelOption {
  providerId: string | null
  providerName: string
  modelName: string
}

export default function ChatPage() {
  const { convId } = useParams<{ convId?: string }>()
  const navigate = useNavigate()
  const { addToast } = useUIStore()
  const {
    conversations, setConversations, updateConversation, addConversation, removeConversation,
    activeStreams, startStream, updateStream, endStream, getStream,
    agentEvents, addAgentEvent, setAgentEvents,
  } = useChatStore()

  const [detail, setDetail] = useState<ConversationDetail | null>(null)
  const detailRef = useRef<ConversationDetail | null>(null)
  const [options, setOptions] = useState<ChatModelOption[]>([])
  const [activeModel, setActiveModel] = useState<ChatModelOption>({
    providerId: null, providerName: 'No Provider', modelName: 'No model available',
  })

  const [input, setInput] = useState('')
  const [retryData, setRetryData] = useState<{ convId: string; text: string; model: ChatModelOption } | null>(null)
  const [modelSearch, setModelSearch] = useState('')
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false)
  const modelDropdownRef = useRef<HTMLDivElement>(null)

  const uid = useAuthStore.getState().user?.id ?? 'anon'
  const lsKey = `agent-settings-${uid}`
  const [toolMode, setToolMode] = useState<'auto'|'none'>(
    () => (localStorage.getItem(lsKey+'.tm') as any) ?? 'auto')
  const [pluginMode, setPluginMode] = useState<'auto'|'none'>(
    () => (localStorage.getItem(lsKey+'.pm') as any) ?? 'auto')
  const [agentMode, setAgentMode] = useState<'plan'|'agent'>(
    () => (localStorage.getItem(lsKey+'.am') as any) ?? 'agent')
  useEffect(() => {
    localStorage.setItem(lsKey+'.tm', toolMode)
    localStorage.setItem(lsKey+'.pm', pluginMode)
    localStorage.setItem(lsKey+'.am', agentMode)
  }, [toolMode, pluginMode, agentMode, lsKey])

  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const streamingActiveRef = useRef<boolean>(false)

  const [searchQuery, setSearchQuery] = useState('')
  const [loadingConv, setLoadingConv] = useState(false)
  const latestFetchId = useRef<string | null>(null)
  const conversationFetchGen = useRef(0)
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null)

  // Get active stream for current conversation
  const activeStream = convId ? activeStreams[convId] : undefined
  const isStreaming = activeStream?.streaming ?? false
  const streamContent = activeStream?.streamContent ?? ''
  const streamSources = activeStream?.streamSources ?? []
  const toolCalls = activeStream?.toolCalls ?? []
  const lastError = activeStream?.lastError ?? null
  const todo = activeStream?.todo ?? []
  const subagents = activeStream?.subagents ?? []
  const verificationStatus = activeStream?.verificationStatus ?? 'none'
  const verificationType = activeStream?.verificationType ?? null

  // Load conversations on mount
  useEffect(() => {
    chatApi.listConversations().then(setConversations).catch(() => {})
  }, [])

  // Load model options on mount
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const urlModel = params.get('model')
    const urlProvider = params.get('provider')
    ;(async () => {
      let providerList: ProviderResponse[] = []
      let modelRows: { provider: ProviderResponse; records: ModelRecord[] }[] = []
      try {
        providerList = await providersApi.list()
        const results = await Promise.allSettled(providerList.map(p => providersApi.getModels(p.id)))
        modelRows = providerList.map((p, i) => ({
          provider: p,
          records: results[i].status === 'fulfilled' ? results[i].value : [],
        }))
      } catch { /* fallback */ }
      const opts: ChatModelOption[] = modelRows.flatMap(({ provider, records }) =>
        records.filter(r => r.enabled && r.status === 'available')
          .map(r => ({ providerId: provider.id, providerName: provider.name, modelName: r.model_id })),
      )
      if (opts.length > 0) {
        setOptions(opts)
        let chosen: ChatModelOption | undefined
        if (urlModel) chosen = opts.find(o => o.modelName === urlModel && (!urlProvider || o.providerId === urlProvider))
        if (!chosen) {
          try {
            const pref = await prefsApi.get()
            if (pref.model_name) chosen = opts.find(o => o.modelName === pref.model_name && (pref.provider_id == null || o.providerId === pref.provider_id))
          } catch { /* ignore */ }
        }
        if (!chosen) chosen = opts.find(o => o.providerName === 'Ollama')
        if (!chosen) chosen = opts[0]
        if (chosen) setActiveModel(chosen)
      } else {
        try {
          const ms = await import('../api/system').then(m => m.systemApi.listModels())
          const ollamaProvider = providerList.find(p => p.name === 'Ollama' || p.provider_type === 'ollama')
          const ollamaId = ollamaProvider?.id ?? null
          const legacy: ChatModelOption[] = ms.map(m => ({ providerId: ollamaId, providerName: 'Ollama', modelName: m.name }))
          setOptions(legacy)
          if (legacy.length > 0) setActiveModel(legacy.find(o => o.modelName === urlModel) ?? legacy[0])
        } catch { /* keep default */ }
      }
    })()
  }, [])

  // Load conversation detail when convId changes
  // NOTE: activeStreams is intentionally NOT a dependency here.
  // Adding it would cause a getConversation fetch on every token event (since updateStream
  // changes activeStreams reference), which would overwrite detail.messages with stale
  // server data and cause the assistant response to disappear mid-stream.
  useEffect(() => {
    if (convId) {
      latestFetchId.current = convId
      const gen = ++conversationFetchGen.current
      setLoadingConv(true)
      chatApi.getConversation(convId)
        .then((d) => {
          if (latestFetchId.current !== convId) return
          if (conversationFetchGen.current !== gen) return
          // Guard: if a stream is active for this conversation, only update detail if
          // the server response contains an assistant message (to avoid overwriting
          // optimistic/streaming state with stale server data)
          // Use getState() to avoid stale closure on activeStreams
          const currentStreams = useChatStore.getState().activeStreams
          const stream = currentStreams[convId]
          if (stream?.streaming) {
            const hasAssistant = d.messages.some(m => m.role === 'assistant')
            if (!hasAssistant) return // Don't overwrite — stream is still in progress
          }
          setDetail(d)
          detailRef.current = d
          setLoadingConv(false)

          // Load persisted agent events for this conversation
          chatApi.getAgentEvents(convId)
            .then(({ events }) => {
              if (latestFetchId.current !== convId) return
              if (events.length > 0) {
                setAgentEvents(convId, events.map(e => ({
                  id: e.id,
                  run_id: e.run_id,
                  sequence: e.sequence,
                  event_type: e.event_type,
                  payload: e.payload,
                  created_at: e.created_at,
                })))
              }
            })
            .catch(() => {}) // Non-fatal
        })
        .catch(() => {
          if (latestFetchId.current !== convId) return
          if (conversationFetchGen.current !== gen) return
          setLoadingConv(false)
          // Don't navigate away if there's an active stream for this conversation
          const currentStreams = useChatStore.getState().activeStreams
          const stream = currentStreams[convId]
          if (!stream?.streaming) {
            navigate('/chat')
          }
        })
    } else {
      setDetail(null)
      detailRef.current = null
      setLoadingConv(false)
    }
  }, [convId, navigate]) // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll when messages or stream content changes
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [detail?.messages, streamContent])

  // Focus input when navigating to a conversation
  useEffect(() => {
    inputRef.current?.focus()
  }, [convId])

  // Cleanup active streams on unmount to prevent memory leaks
  useEffect(() => {
    return () => {
      // Abort any active streams when component unmounts
      if (convId) {
        const stream = activeStreams[convId]
        if (stream?.abortController) {
          stream.abortController.abort()
        }
      }
    }
  }, []) // Empty deps — only run on unmount

  // Close model dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (modelDropdownRef.current && !modelDropdownRef.current.contains(e.target as Node)) {
        setModelDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Stop handler - atomically abort and clear all streaming state
  const handleStop = useCallback(() => {
    if (!convId) return
    const stream = activeStreams[convId]
    if (!stream) return

    // Abort the controller first (this will trigger the AbortError in doSend)
    if (stream.abortController) {
      stream.abortController.abort()
    }

    // Atomically clear ALL streaming state
    // The doSend catch block will also handle this, but we do it here
    // to ensure immediate UI update (Stop button disappears instantly)
    updateStream(convId, {
      streaming: false,
      streamContent: '',
      streamSources: [],
      toolCalls: [],
      lastError: 'Cancelled',
      agentState: 'cancelled',
      todo: [],
      subagents: [],
      verificationStatus: 'none',
      verificationType: null,
    })
  }, [convId, activeStreams, updateStream])

  // SSE stream processor — handles all event parsing, token refresh, and state updates
  const processSSEStream = useCallback(async (resp: Response, convId: string, controller: AbortController, runId: string) => {
    const reader = resp.body!.getReader()
    const decoder = new TextDecoder()
    let buf = '', acc = ''
    let evidenceReceived: CitationSource[] = []
    let tcAcc: ToolCall[] = []
    let doneProcessed = false
    let finalAssistantContent = '' // Track final content for reconciliation
    let eventSequence = 0 // Track sequence for durable events

    // Helper to check if this stream is still the active one (filters stale events)
    const isStillActive = (): boolean => {
      const stream = getStream(convId)
      return stream?.runId === runId && stream?.streaming === true
    }

    // Helper to store an agent event in durable state
    const storeEvent = (eventType: string, payload: Record<string, unknown>) => {
      eventSequence++
      const evt = {
        id: `evt-${runId}-${eventSequence}`,
        run_id: runId,
        sequence: eventSequence,
        event_type: eventType,
        payload,
        created_at: new Date().toISOString(),
      }
      addAgentEvent(convId, evt)
    }

    while (true) {
      let readResult: Awaited<ReturnType<typeof reader.read>>
      try {
        readResult = await reader.read()
      } catch (readErr: any) {
        // TASK 5: Stream read failure after done event is normal — the server
        // closed the connection. Only treat as error if we haven't seen a done
        // event yet. TypeError occurs when the stream is already closed.
        if (doneProcessed || acc) {
          console.debug('[SSE] Stream read error after completion (normal):', readErr?.name || readErr)
          break
        }
        throw readErr
      }
      if (readResult.done) break
      const value = readResult.value
      buf += decoder.decode(value, { stream: true })
      // Handle both \n and \r\n line endings per SSE spec
      const lines = buf.split(/\r?\n/)
      buf = lines.pop() ?? ''

      let ev = ''
      for (const line of lines) {
        // SSE spec: lines starting with : are comments (heartbeat) — skip
        if (line.startsWith(':') || line === '') {
          continue
        }
        if (line.startsWith('event:')) ev = line.slice(6).trim()
        else if (line.startsWith('data:') && ev) {
          const raw = line.slice(5).trim()
          let d: any
          try {
            d = JSON.parse(raw)
          } catch (e) {
            console.warn('[SSE] Failed to parse JSON for event:', ev, raw)
            ev = ''
            continue
          }

          // Filter stale events from old runs
          if (!isStillActive() && ev !== 'done' && ev !== 'error') {
            console.debug('[SSE] Ignoring stale event:', ev, 'for conv:', convId)
            ev = ''
            continue
          }

          if (ev === 'token') {
            acc += d.delta
            finalAssistantContent = acc // Track the accumulated content
            updateStream(convId, { streamContent: acc })
          } else if (ev === 'evidence') {
            evidenceReceived = d.sources || []
            updateStream(convId, { streamSources: evidenceReceived })
          } else if (ev === 'tool_call') {
            tcAcc = [...tcAcc, {
              call_id: d.call_id, tool: d.tool, status: 'running',
              input_summary: d.input_summary, reasoning: d.reasoning,
              timestamp: Date.now(),
            }]
            updateStream(convId, { toolCalls: [...tcAcc] })
            storeEvent('tool_call', d)
          } else if (ev === 'tool_started') {
            tcAcc = tcAcc.map(tc => tc.call_id === d.call_id ? {...tc, status: 'running'} : tc)
            updateStream(convId, { toolCalls: [...tcAcc] })
          } else if (ev === 'tool_result') {
            tcAcc = tcAcc.map(tc => tc.call_id === d.call_id ? {
              ...tc, status: d.status === 'success' ? 'success' : 'error',
              result_summary: d.result_summary, duration_ms: d.duration_ms,
              error: d.error,
            } : tc)
            updateStream(convId, { toolCalls: [...tcAcc] })
            storeEvent('tool_result', d)
          } else if (ev === 'tool_error') {
            tcAcc = tcAcc.map(tc => tc.call_id === d.call_id ? {
              ...tc, status: 'error', error: d.error,
            } : tc)
            updateStream(convId, { toolCalls: [...tcAcc] })
            storeEvent('tool_error', d)
          } else if (ev === 'tool_timeout') {
            tcAcc = tcAcc.map(tc => tc.call_id === d.call_id ? {
              ...tc, status: 'timeout', error: d.error, duration_ms: d.duration_ms,
            } : tc)
            updateStream(convId, { toolCalls: [...tcAcc] })
            storeEvent('tool_timeout', d)
          } else if (ev === 'todo_updated') {
            updateStream(convId, { todo: d.tasks || [] })
            storeEvent('todo_updated', d)
          } else if (ev === 'todo_task_added') {
            const stream = getStream(convId)
            if (stream) {
              updateStream(convId, {
                todo: [...stream.todo, {
                  id: d.task_id, description: d.description,
                  status: d.status || 'pending',
                }],
              })
            }
          } else if (ev === 'agent_state') {
            updateStream(convId, { agentState: d.state || null })
          } else if (ev === 'plan_created') {
            // Plan created — update agent state to show planning is done
            updateStream(convId, { agentState: d.state || 'planning' })
            storeEvent('plan_created', d)
          } else if (ev === 'plan_updated') {
            // Plan updated during replanning
            updateStream(convId, { agentState: d.state || 'replanning' })
            storeEvent('plan_updated', d)
          } else if (ev === 'decision') {
            // Reasoning decision — show activity
            updateStream(convId, { agentState: d.activity || d.state || 'reasoning' })
          } else if (ev === 'verification') {
            // Unified verification event from runtime
            const status = d.verified ? 'passed' : 'failed'
            updateStream(convId, {
              verificationStatus: status,
              verificationType: d.type || 'output',
            })
          } else if (ev === 'verification_started') {
            updateStream(convId, {
              verificationStatus: 'started',
              verificationType: d.type || null,
            })
            storeEvent('verification_started', d)
          } else if (ev === 'verification_passed') {
            updateStream(convId, {
              verificationStatus: 'passed',
              verificationType: d.type || null,
            })
            storeEvent('verification_passed', d)
          } else if (ev === 'verification_failed') {
            updateStream(convId, {
              verificationStatus: 'failed',
              verificationType: d.type || null,
            })
            storeEvent('verification_failed', d)
          } else if (ev === 'cancelled') {
            // Cancellation — atomically clear all streaming state
            updateStream(convId, {
              streaming: false,
              lastError: 'Cancelled',
              agentState: 'cancelled',
            })
          } else if (ev === 'retry') {
            // Tool retry — update agent state
            updateStream(convId, { agentState: d.reason || 'retrying' })
            storeEvent('retry', d)
          } else if (ev === 'observation') {
            // Observation from tool execution
            updateStream(convId, { agentState: d.description || 'observing' })
            storeEvent('observation', d)
          } else if (ev === 'final_response') {
            // Final response content — store in durable state before done clears streaming
            // This is the critical handoff: response content persisted to DB by backend,
            // now committed to durable frontend state
            storeEvent('final_response', d)
          } else if (ev === 'agent_started') {
            storeEvent('agent_started', d)
          } else if (ev === 'subagent_spawned') {
            const stream = getStream(convId)
            if (stream) {
              updateStream(convId, {
                subagents: [...stream.subagents, {
                  session_id: d.session_id,
                  agent_type: d.agent_type,
                  task: d.task,
                  status: 'running',
                }],
              })
            }
          } else if (ev === 'subagent_completed') {
            const stream = getStream(convId)
            if (stream) {
              updateStream(convId, {
                subagents: stream.subagents.map(s =>
                  s.session_id === d.session_id
                    ? { ...s, status: 'completed' }
                    : s
                ),
              })
            }
          } else if (ev === 'done') {
            // Final done event — atomically clear ALL streaming state
            // This is idempotent: if already processed, subsequent done events are ignored
            storeEvent('done', d)
            if (!doneProcessed) {
              doneProcessed = true
              // CRITICAL: Commit streamed content to detail.messages BEFORE clearing streaming.
              // This prevents the "response disappears" gap where StreamingBubble unmounts
              // but detail.messages doesn't have the assistant message yet.
              // React 18 batches setDetail + updateStream in the same render cycle,
              // so there is never a state where the response exists in neither source.
              if (acc) {
                const assistantMsg = {
                  id: 'done-'+Date.now()+'-'+runId,
                  role: 'assistant' as const,
                  content: acc,
                  token_count: null,
                  finish_reason: null,
                  created_at: new Date().toISOString(),
                }
                setDetail(prev => prev ? {
                  ...prev,
                  messages: [...prev.messages, assistantMsg],
                  message_count: prev.messages.length + 1,
                } : prev)
              }
              updateStream(convId, {
                streaming: false,
                agentState: d.state || null,
                lastError: null,
              })
            }
          } else if (ev === 'error') {
            // Error — atomically clear streaming state and show error
            storeEvent('error', d)
            updateStream(convId, {
              streaming: false,
              lastError: d.message || 'Unknown error',
              agentState: 'failed',
            })
            addToast({ type: 'error', title: 'AI Error', message: d.message })
          }
          ev = ''
        }
      }
    }

    // Stream complete — fetch updated conversation with retry for DB commit latency
    if (doneProcessed || acc) {
      const MAX_RETRIES = 3
      for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
        try {
          const updated = await chatApi.getConversation(convId)
          const hasAssistant = updated.messages.some(m => m.role === 'assistant')
          if (hasAssistant) {
            setDetail(updated)
            detailRef.current = updated
            updateConversation(convId, { title: updated.title, message_count: updated.messages.length })
            break
          }
          // If no assistant message yet and we have streamed content, wait briefly and retry
          if (attempt < MAX_RETRIES - 1 && finalAssistantContent) {
            await new Promise(r => setTimeout(r, 300 * (attempt + 1)))
          } else {
            // Last attempt — only use server data if it has an assistant message.
            // If not, keep current detail (which already has the committed assistant content
            // from the done event handler above). Never overwrite with stale server data.
            const currentDetail = useChatStore.getState().activeStreams[convId]
            const detailHasAssistant = detailRef.current?.messages.some(m => m.role === 'assistant')
            if (hasAssistant || !detailHasAssistant) {
              setDetail(updated)
              detailRef.current = updated
            }
            // If detail already has assistant and server doesn't, preserve the committed content
          }
        } catch {
          // Network error — keep current detail state
          break
        }
      }
    }
  }, [updateStream, getStream, addToast, setDetail, updateConversation, addAgentEvent])

  // Core send function - runs in background even if user navigates away
  const doSend = useCallback(async (text: string, convIdParam: string | undefined, model: ChatModelOption) => {
    if (!text.trim()) return
    // agentMode controls whether AgentRuntime is used
    // toolMode controls tool availability (auto/none), independent of agent mode
    const useAgent = agentMode === 'agent'

    let currentConvId = convIdParam
    if (!currentConvId) {
      const conv = await chatApi.createConversation({ model_name: model.modelName, title: text.slice(0, 80) })
      currentConvId = conv.id
      addConversation(conv)
    }

    // Start stream in store BEFORE navigate so the streaming guard in the
    // conversation detail useEffect protects optimistic state from being overwritten.
    // With the merged route (<Route path="/chat/:convId?">), navigate does NOT cause
    // a remount, so setDetail in this closure remains valid.
    const controller = new AbortController()
    const stream = startStream(currentConvId)
    const runId = stream.runId
    streamingActiveRef.current = true
    updateStream(currentConvId, {
      streaming: true,
      streamContent: '',
      streamSources: [],
      toolCalls: [],
      lastError: null,
      abortController: controller,
      todo: [],
      subagents: [],
      agentState: null,
      verificationStatus: 'none',
    })

    // Optimistically add user message to detail so it's visible immediately
    const userMsg = {
      id: 'tmp-'+Date.now(), role: 'user' as const, content: text,
      token_count: null, finish_reason: null,
      created_at: new Date().toISOString(),
    }
    if (currentConvId === convId) {
      // Viewing this conversation — add to existing detail
      setDetail(prev => prev ? {...prev, messages: [...prev.messages, userMsg]} : prev)
    } else {
      // New conversation — create minimal detail so user sees their message
      setDetail({
        id: currentConvId!, title: text.slice(0, 80),
        model_name: model.modelName, system_prompt: null, context_mode: 'chat',
        created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        message_count: 1, messages: [userMsg],
      })
      // Navigate AFTER stream is started and optimistic state is set.
      // With merged route, this updates the URL param without remounting.
      navigate(`/chat/${currentConvId}`, { replace: true })
    }

    prefsApi.set(model.providerId, model.modelName).catch(() => {})

    // Proactively refresh token before starting stream to avoid mid-stream 401
    try {
      const refreshResp = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
        method: 'POST',
        credentials: 'include',  // send httpOnly refresh cookie
      })
      if (refreshResp.ok) {
        const { access_token } = await refreshResp.json()
        if (access_token) useAuthStore.getState().setToken(access_token)
      }
    } catch { /* use existing token */ }

    const endpoint = useAgent
      ? `${API_BASE}/api/v1/chat/conversations/${currentConvId}/agent`
      : `${API_BASE}/api/v1/chat/conversations/${currentConvId}/messages`

    const body: Record<string, unknown> = {
      content: text, model_name: model.modelName, provider_id: model.providerId,
    }
    if (useAgent) {
      body.tool_mode = toolMode
      body.plugin_mode = pluginMode
      body.agent_mode = agentMode
    }

    try {
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${useAuthStore.getState().accessToken}`,
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      })

      // If 401, try one refresh + retry
      if (resp.status === 401) {
        try {
          const retryRefresh = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
            method: 'POST',
            credentials: 'include',
          })
          if (retryRefresh.ok) {
            const { access_token } = await retryRefresh.json()
            if (access_token) {
              useAuthStore.getState().setToken(access_token)
              const retryResp = await fetch(endpoint, {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  Authorization: `Bearer ${access_token}`,
                },
                body: JSON.stringify(body),
                signal: controller.signal,
              })
              if (!retryResp.ok || !retryResp.body) throw new Error(`Stream failed (${retryResp.status})`)
              return await processSSEStream(retryResp, currentConvId!, controller, runId)
            }
          }
        } catch { /* fall through to error */ }
        throw new Error('Authentication failed — please log in again')
      }

      if (!resp.ok || !resp.body) throw new Error(`Stream failed (${resp.status})`)

      await processSSEStream(resp, currentConvId!, controller, runId)
    } catch (err: any) {
      // Check if this stream is still the active one before updating state
      const currentStream = getStream(currentConvId!)
      if (currentStream?.runId !== runId) return // Stale error, ignore

      // TASK 5: If we already received content, the "network error" is a false
      // alarm — the server closed normally but the client saw a read error.
      // Only surface the error if we have NO content at all.
      const hasStreamedContent = currentStream?.streamContent
      if (hasStreamedContent && !err?.message?.includes('401')) {
        console.debug('[SSE] Ignoring post-completion error:', err?.message)
        // Don't show error toast — content was already delivered
        return
      } else if (err?.name === 'AbortError') {
        // User cancelled — atomically clear all streaming state
        updateStream(currentConvId!, {
          streaming: false,
          lastError: 'Cancelled',
          agentState: 'cancelled',
        })
        setRetryData({ convId: currentConvId!, text, model })
        return
      }
      // Error — atomically clear streaming state and show error
      updateStream(currentConvId!, {
        streaming: false,
        lastError: err?.message || 'Send failed',
        agentState: 'failed',
      })
      setRetryData({ convId: currentConvId!, text, model })
      addToast({ type: 'error', title: 'Send failed', message: err?.message })
      // NOTE: Do NOT fetch conversation on error — the optimistic user message
      // should remain visible with the error state. The user can retry.
    } finally {
      streamingActiveRef.current = false
      // Only end stream if this is still the active run
      const currentStream = getStream(currentConvId!)
      if (currentStream?.runId === runId) {
        endStream(currentConvId!)
      }
      inputRef.current?.focus()
      // Refresh conversation list
      chatApi.listConversations().then(setConversations).catch(() => {})
    }
  }, [toolMode, pluginMode, agentMode, navigate, addToast, startStream, updateStream, endStream, updateConversation, addConversation, setConversations, processSSEStream, getStream, setDetail, convId])

  const handleSend = useCallback(() => {
    const text = input.trim()
    if (!text || isStreaming) return
    setInput('')
    doSend(text, convId, activeModel)
  }, [input, isStreaming, convId, activeModel, doSend])

  const handleRetry = useCallback(() => {
    if (!retryData || isStreaming) return
    // Use the current URL's convId (not stale one from when error occurred)
    doSend(retryData.text, convId || retryData.convId, retryData.model)
  }, [retryData, isStreaming, convId, doSend])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleRename = async (id: string) => {
    const current = conversations.find(c => c.id === id)
    const newTitle = window.prompt('Rename conversation:', current?.title || '')
    if (!newTitle?.trim()) return
    try {
      await chatApi.renameConversation(id, newTitle.trim())
      updateConversation(id, { title: newTitle.trim() })
      if (detail?.id === id) setDetail(prev => prev ? { ...prev, title: newTitle.trim() } : prev)
      addToast({ type: 'success', title: 'Renamed' })
    } catch {
      addToast({ type: 'error', title: 'Rename failed' })
    }
  }

  const handleDelete = async (id: string) => {
    const conv = conversations.find(c => c.id === id)
    if (!window.confirm(`Delete "${conv?.title || 'conversation'}"?\n\nThis will permanently remove this chat history.`)) return
    try {
      await chatApi.deleteConversation(id)
      removeConversation(id)
      if (detail?.id === id) { setDetail(null); navigate('/chat', { replace: true }) }
      addToast({ type: 'info', title: 'Conversation deleted' })
    } catch {
      addToast({ type: 'error', title: 'Delete failed' })
    }
  }

  const filtered = conversations.filter(c =>
    !searchQuery || (c.title ?? '').toLowerCase().includes(searchQuery.toLowerCase())
  )

  const dateGroups = (() => {
    const groups: Record<string, ConversationResponse[]> = {}
    const nowIST = istDateParts(new Date())
    const yesterdayIST = { ...nowIST }
    const yDate = new Date(Date.UTC(nowIST.y, nowIST.m - 1, nowIST.day - 1))
    yesterdayIST.y = yDate.getUTCFullYear(); yesterdayIST.m = yDate.getUTCMonth() + 1; yesterdayIST.day = yDate.getUTCDate()
    for (const c of filtered) {
      const p = istDateParts(c.updated_at)
      let label = 'Older'
      if (p.y === nowIST.y && p.m === nowIST.m && p.day === nowIST.day) label = 'Today'
      else if (p.y === yesterdayIST.y && p.m === yesterdayIST.m && p.day === yesterdayIST.day) label = 'Yesterday'
      ;(groups[label] = groups[label] ?? []).push(c)
    }
    return groups
  })()

  const timeAgo = (dateStr: string) => {
    const diff = Date.now() - parseServerDate(dateStr).getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'now'
    if (mins < 60) return `${mins}m`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h`
    return `${Math.floor(hrs / 24)}d`
  }

  // Check if a conversation has an active stream (for sidebar indicator)
  const isConvStreaming = (id: string) => activeStreams[id]?.streaming ?? false

  const [mobileConvOpen, setMobileConvOpen] = useState(false)

  // Close mobile conversation list on route change
  useEffect(() => {
    setMobileConvOpen(false)
  }, [convId])

  return (
    <div className="flex h-[calc(100vh-3.5rem-3rem)] gap-0 relative">
      {/* Mobile conversation list backdrop */}
      {mobileConvOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-30 lg:hidden"
          onClick={() => setMobileConvOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Conversation list — desktop */}
      <aside className="hidden lg:flex w-64 flex-shrink-0 flex-col bg-surface-raised border-r border-surface-border rounded-l-lg overflow-hidden">
        <div className="p-3 space-y-2 border-b border-surface-border">
          <button
            onClick={() => { navigate('/chat') }}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-cyan-600 text-white rounded-md text-sm font-medium hover:bg-cyan-500 transition-colors"
          >
            + New Chat
          </button>
          {conversations.length > 0 && (
            <input type="search" value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
              placeholder="Search conversations…" aria-label="Search conversations"
              className="w-full rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-xs text-neutral-200 placeholder-neutral-500 focus:outline-none focus:ring-1 focus:ring-cyan-500" />
          )}
        </div>
        <div className="flex-1 overflow-y-auto">
          {loadingConv ? (
            <div className="flex items-center justify-center py-8 gap-2 text-xs text-neutral-500">
              <span className="animate-spin h-3 w-3 border-2 border-surface-border border-t-cyan-400 rounded-full inline-block" />
              Loading…
            </div>
          ) : conversations.length === 0 ? (
            <p className="text-xs text-neutral-500 text-center mt-6 px-3">No conversations yet</p>
          ) : filtered.length === 0 ? (
            <p className="text-xs text-neutral-500 text-center mt-6 px-3">No matches for "{searchQuery}"</p>
          ) : (
            Object.entries(dateGroups).map(([group, items]) => (
              <div key={group}>
                <p className="px-3 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-cyan-700 select-none">{group}</p>
                {items.map(c => (
                  <div key={c.id}
                    className={`group relative flex items-center border-b border-surface-border transition-colors
                      ${convId === c.id ? 'bg-cyan-500/10 border-l-2 border-l-cyan-500' : 'hover:bg-surface-muted'}`}>
                    <button onClick={() => { navigate(`/chat/${c.id}`); setMenuOpenId(null) }}
                      className={`flex-1 text-left px-3 py-2 text-sm min-w-0 ${convId === c.id ? 'text-cyan-400' : 'text-neutral-300'}`}>
                      <div className="truncate font-medium flex items-center gap-1.5">
                        {c.title || 'New conversation'}
                        {isConvStreaming(c.id) && (
                          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse flex-shrink-0" />
                        )}
                      </div>
                      <div className="text-[10px] text-neutral-500 mt-0.5 flex items-center gap-1">
                        <span>{timeAgo(c.updated_at)}</span>
                        <span>·</span>
                        <span className="truncate">{c.model_name}</span>
                      </div>
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); setMenuOpenId(menuOpenId === c.id ? null : c.id) }}
                      className="absolute right-1 top-1/2 -translate-y-1/2 p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-surface-muted transition-opacity"
                      aria-label="Conversation options">
                      <span className="text-xs text-neutral-500">⋮</span>
                    </button>
                    {menuOpenId === c.id && (
                      <>
                        <div className="fixed inset-0 z-10" onClick={() => setMenuOpenId(null)} />
                        <div className="absolute right-2 top-full mt-0 z-20 w-32 bg-surface-raised rounded-md shadow-lg border border-surface-border py-1">
                          <button onClick={() => { setMenuOpenId(null); handleRename(c.id) }}
                            className="block w-full text-left px-3 py-1.5 text-xs text-neutral-300 hover:bg-surface-muted">
                            ✎ Rename
                          </button>
                          <button onClick={() => { setMenuOpenId(null); handleDelete(c.id) }}
                            className="block w-full text-left px-3 py-1.5 text-xs text-red-400 hover:bg-red-900/20">
                            🗑 Delete
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                ))}
              </div>
            ))
          )}
        </div>
      </aside>

      {/* Conversation list — mobile drawer */}
      <aside className={`fixed inset-y-0 left-0 w-72 flex flex-col bg-surface-raised border-r border-surface-border z-40 lg:hidden transition-transform duration-200 ${
        mobileConvOpen ? 'translate-x-0' : '-translate-x-full'
      }`}>
        <div className="p-3 space-y-2 border-b border-surface-border">
          <div className="flex items-center justify-between">
            <button
              onClick={() => { navigate('/chat'); setMobileConvOpen(false) }}
              className="flex-1 flex items-center justify-center gap-2 px-3 py-2 bg-cyan-600 text-white rounded-md text-sm font-medium hover:bg-cyan-500 transition-colors"
            >
              + New Chat
            </button>
            <button onClick={() => setMobileConvOpen(false)} className="ml-2 p-2 text-neutral-500 hover:text-neutral-300" aria-label="Close conversations">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          {conversations.length > 0 && (
            <input type="search" value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
              placeholder="Search conversations…" aria-label="Search conversations"
              className="w-full rounded-md border border-surface-border bg-surface px-2.5 py-1.5 text-xs text-neutral-200 placeholder-neutral-500 focus:outline-none focus:ring-1 focus:ring-cyan-500" />
          )}
        </div>
        <div className="flex-1 overflow-y-auto">
          {loadingConv ? (
            <div className="flex items-center justify-center py-8 gap-2 text-xs text-neutral-500">
              <span className="animate-spin h-3 w-3 border-2 border-surface-border border-t-cyan-400 rounded-full inline-block" />
              Loading…
            </div>
          ) : conversations.length === 0 ? (
            <p className="text-xs text-neutral-500 text-center mt-6 px-3">No conversations yet</p>
          ) : filtered.length === 0 ? (
            <p className="text-xs text-neutral-500 text-center mt-6 px-3">No matches for "{searchQuery}"</p>
          ) : (
            Object.entries(dateGroups).map(([group, items]) => (
              <div key={group}>
                <p className="px-3 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-cyan-700 select-none">{group}</p>
                {items.map(c => (
                  <div key={c.id}
                    className={`group relative flex items-center border-b border-surface-border transition-colors
                      ${convId === c.id ? 'bg-cyan-500/10 border-l-2 border-l-cyan-500' : 'hover:bg-surface-muted'}`}>
                    <button onClick={() => { navigate(`/chat/${c.id}`); setMobileConvOpen(false); setMenuOpenId(null) }}
                      className={`flex-1 text-left px-3 py-2 text-sm min-w-0 ${convId === c.id ? 'text-cyan-400' : 'text-neutral-300'}`}>
                      <div className="truncate font-medium flex items-center gap-1.5">
                        {c.title || 'New conversation'}
                        {isConvStreaming(c.id) && (
                          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse flex-shrink-0" />
                        )}
                      </div>
                      <div className="text-[10px] text-neutral-500 mt-0.5 flex items-center gap-1">
                        <span>{timeAgo(c.updated_at)}</span>
                        <span>·</span>
                        <span className="truncate">{c.model_name}</span>
                      </div>
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); setMenuOpenId(menuOpenId === c.id ? null : c.id) }}
                      className="absolute right-1 top-1/2 -translate-y-1/2 p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-surface-muted transition-opacity"
                      aria-label="Conversation options">
                      <span className="text-xs text-neutral-500">⋮</span>
                    </button>
                    {menuOpenId === c.id && (
                      <>
                        <div className="fixed inset-0 z-10" onClick={() => setMenuOpenId(null)} />
                        <div className="absolute right-2 top-full mt-0 z-20 w-32 bg-surface-raised rounded-md shadow-lg border border-surface-border py-1">
                          <button onClick={() => { setMenuOpenId(null); handleRename(c.id) }}
                            className="block w-full text-left px-3 py-1.5 text-xs text-neutral-300 hover:bg-surface-muted">
                            ✎ Rename
                          </button>
                          <button onClick={() => { setMenuOpenId(null); handleDelete(c.id) }}
                            className="block w-full text-left px-3 py-1.5 text-xs text-red-400 hover:bg-red-900/20">
                            🗑 Delete
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                ))}
              </div>
            ))
          )}
        </div>
      </aside>

      {/* Chat area */}
      <div className="flex flex-col flex-1 bg-surface rounded-r-lg overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center gap-2 px-3 py-2.5 bg-surface-raised border-b border-surface-border flex-shrink-0">
          {/* Mobile: toggle conversation list */}
          <button onClick={() => setMobileConvOpen(true)}
            className="lg:hidden p-1.5 rounded-lg text-neutral-500 hover:bg-surface-muted hover:text-neutral-300 transition-colors flex-shrink-0"
            aria-label="Open conversations">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
            </svg>
          </button>
          <div className="relative" ref={modelDropdownRef}>
            <button
              onClick={() => { setModelDropdownOpen(v => !v); setModelSearch('') }}
              className="text-sm border border-surface-border rounded-md px-2 py-1 bg-surface text-neutral-200 focus:outline-none focus:ring-2 focus:ring-cyan-500 max-w-[200px] md:max-w-xs text-left flex items-center gap-1"
              aria-label="Select AI model"
            >
              <span className="truncate">{activeModel.providerName} / {activeModel.modelName}</span>
              <svg className="w-3 h-3 shrink-0 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
            </button>
            {modelDropdownOpen && (
              <div className="absolute z-50 mt-1 w-72 md:w-80 max-h-72 overflow-hidden bg-surface-raised border border-surface-border rounded-lg shadow-xl flex flex-col">
                <div className="p-2 border-b border-surface-border">
                  <input
                    autoFocus
                    type="text"
                    placeholder="Search models..."
                    value={modelSearch}
                    onChange={e => setModelSearch(e.target.value)}
                    className="w-full text-sm px-2.5 py-1.5 rounded-md border border-surface-border bg-surface text-neutral-200 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                  />
                </div>
                <div className="overflow-y-auto flex-1">
                  {(() => {
                    const q = modelSearch.toLowerCase()
                    const grouped: Record<string, ChatModelOption[]> = {}
                    for (const o of options) {
                      if (q && !o.modelName.toLowerCase().includes(q) && !o.providerName.toLowerCase().includes(q)) continue
                      ;(grouped[o.providerName] = grouped[o.providerName] || []).push(o)
                    }
                    const entries = Object.entries(grouped)
                    if (entries.length === 0) {
                      return <div className="px-3 py-4 text-sm text-neutral-500 text-center">No models found</div>
                    }
                    return entries.map(([pname, opts]) => (
                      <div key={pname}>
                        <div className="px-3 pt-2 pb-0.5 text-[10px] font-semibold uppercase tracking-wider text-cyan-700 select-none">{pname}</div>
                        {opts.map(o => (
                          <button
                            key={`${o.providerId}|${o.modelName}`}
                            onClick={() => {
                              setActiveModel(o)
                              prefsApi.set(o.providerId, o.modelName).catch(() => {})
                              setModelDropdownOpen(false)
                            }}
                            className={`w-full text-left px-3 py-1.5 text-sm hover:bg-surface-muted transition-colors ${
                              o.providerId === activeModel.providerId && o.modelName === activeModel.modelName
                                ? 'bg-cyan-500/10 text-cyan-400 font-medium'
                                : 'text-neutral-300'
                            }`}
                          >
                            {o.modelName}
                          </button>
                        ))}
                      </div>
                    ))
                  })()}
                </div>
              </div>
            )}
          </div>
          <span className="text-xs text-neutral-500 truncate max-w-40">{activeModel.providerName}</span>
          <span className={`text-xs rounded px-2 py-0.5 flex items-center gap-1 ${
            activeModel.providerId
              ? 'text-blue-400 bg-blue-900/20 border border-blue-800/40'
              : 'text-cyan-400 bg-cyan-500/10 border border-cyan-800/40'
          }`}>
            <span aria-hidden="true">{activeModel.providerId ? '☁️' : '🔒'}</span>
            {activeModel.providerId ? 'Cloud' : 'Local'}
          </span>
          {isStreaming && (
            <span className="text-xs text-cyan-400 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
              Streaming…
            </span>
          )}
        </div>

        {/* Agent Settings */}
        <details className="w-full border-b border-surface-border bg-surface-raised/60">
          <summary className="cursor-pointer select-none px-4 py-1.5 text-xs font-medium text-cyan-700">
            ⚙️ Agent Settings ({agentMode === 'agent' ? 'agent mode' : 'plan mode'} · tools: {toolMode})
          </summary>
          <div className="px-4 py-2 grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
            <div>
              <p className="font-medium mb-1 text-neutral-400">Mode</p>
              <select value={agentMode} onChange={e => setAgentMode(e.target.value as any)}
                className="w-full rounded border border-surface-border bg-surface px-2 py-1 text-neutral-200"
                aria-label="Agent mode">
                <option value="plan">Plan (analyze only)</option>
                <option value="agent">Agent (autonomous)</option>
              </select>
            </div>
            <div>
              <p className="font-medium mb-1 text-neutral-400">Tools</p>
              <select value={toolMode} onChange={e => setToolMode(e.target.value as any)}
                className="w-full rounded border border-surface-border bg-surface px-2 py-1 text-neutral-200"
                aria-label="Tools mode">
                <option value="auto">Auto</option>
                <option value="none">None</option>
              </select>
            </div>
            <div>
              <p className="font-medium mb-1 text-neutral-400">Model</p>
              <p className="text-[11px] text-neutral-500 truncate">{activeModel.providerName} / {activeModel.modelName}</p>
            </div>
          </div>
        </details>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-3 md:px-4 py-4">
          {!convId && !isStreaming && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="text-4xl mb-3" aria-hidden="true">💬</div>
              {options.length === 0 ? (
                <>
                  <p className="text-neutral-400">No models available</p>
                  <p className="text-xs text-neutral-500 mt-1">Add a provider in LLM Providers to start chatting</p>
                  <button onClick={() => navigate('/providers')} className="mt-3 px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-medium hover:bg-cyan-500">
                    + Add Provider
                  </button>
                </>
              ) : (
                <>
                  <p className="text-neutral-400">Start a new conversation</p>
                  <p className="text-xs text-neutral-500 mt-1">Press Ctrl+Enter to send</p>
                </>
              )}
            </div>
          )}

          {detail?.messages.map((m) => (
            <MessageBubble key={m.id} msg={m} />
          ))}

          {/* Durable agent timeline — persists after streaming ends */}
          {convId && agentEvents[convId]?.length > 0 && (
            <AgentTimeline
              events={agentEvents[convId]}
              isStreaming={isStreaming}
            />
          )}

          {toolCalls.length > 0 && isStreaming && (
            <ToolCallCard calls={toolCalls} />
          )}

          {(todo.length > 0 || subagents.length > 0 || verificationStatus !== 'none' || activeStream?.agentState) && isStreaming && (
            <AgentActivity
              todo={todo}
              subagents={subagents}
              verificationStatus={verificationStatus}
              verificationType={verificationType}
              agentState={activeStream?.agentState ?? null}
            />
          )}

          {isStreaming && (
            <StreamingBubble
              content={streamContent}
              model={`${activeModel.providerName} / ${activeModel.modelName}`}
              sources={streamSources}
              onStop={handleStop}
            />
          )}

          {!isStreaming && detail?.messages.length && (() => {
            const lastAssistant = [...detail.messages].reverse().find(m => m.role === 'assistant')
            if (!lastAssistant?.metadata?.evidence?.sources) return null
            return (
              <EvidencePanel
                sources={lastAssistant.metadata.evidence.sources as CitationSource[]}
              />
            )
          })()}

          {lastError && !isStreaming && (
            <div className="mb-3 px-4 py-3 rounded-lg bg-red-900/20 border border-red-800/40 text-xs">
              <div className="flex items-start gap-2">
                <span className="text-red-400 mt-0.5">⚠</span>
                <div className="flex-1 min-w-0">
                  <p className="text-red-400 font-medium">Failed to get response</p>
                  <p className="text-red-300/80 mt-0.5 break-words">{lastError}</p>
                  <p className="text-neutral-500 mt-1">Model: {activeModel.modelName} · Provider: {activeModel.providerName}</p>
                </div>
                {retryData && (
                  <button onClick={handleRetry}
                    className="px-2 py-1 rounded bg-red-900/30 hover:bg-red-900/50 text-red-400 font-medium transition-colors flex-shrink-0">
                    ↻ Retry
                  </button>
                )}
                <button onClick={() => { updateStream(convId!, { lastError: null }); setRetryData(null) }}
                  className="px-1 text-neutral-500 hover:text-neutral-300 flex-shrink-0">✕</button>
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input bar */}
        <div className="px-3 md:px-4 py-3 bg-surface-raised border-t border-surface-border flex-shrink-0">
          {/* Model indicator */}
          <div className="flex items-center gap-2 mb-2 text-[10px] text-neutral-500">
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-500" />
            <span>{activeModel.providerName}</span>
            <span>·</span>
            <span className="text-neutral-400">{activeModel.modelName}</span>
            {activeModel.providerId && <span className="text-cyan-600">(connected)</span>}
          </div>
          <div className="flex gap-2 items-end">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              placeholder="Type a message… (Ctrl+Enter to send)"
              disabled={isStreaming}
              className="flex-1 resize-none rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-neutral-200 placeholder-neutral-500 shadow-sm focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:opacity-50 max-h-40"
              aria-label="Chat message input"
            />
            {isStreaming ? (
              <button
                onClick={handleStop}
                className="flex-shrink-0 bg-red-600 text-white rounded-md px-4 py-2 text-sm font-medium hover:bg-red-500 transition-colors"
                aria-label="Stop generation"
              >
                ■ Stop
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!input.trim()}
                className="flex-shrink-0 bg-cyan-600 text-white rounded-md px-4 py-2 text-sm font-medium hover:bg-cyan-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                aria-label="Send message"
              >
                Send
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
