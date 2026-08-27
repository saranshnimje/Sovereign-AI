import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { parseServerDate, istDateParts } from '../utils/dates'
import { chatApi, ConversationDetail, ConversationResponse, MessageResponse, CitationSource } from '../api/chat'
import { providersApi, prefsApi, ModelRecord, ProviderResponse } from '../api/providers'
import { useAuthStore } from '../stores/authStore'
import { useUIStore } from '../stores/uiStore'
import MessageBubble from '../components/chat/MessageBubble'
import StreamingBubble from '../components/chat/StreamingBubble'
import EvidencePanel from '../components/chat/EvidencePanel'
import ToolCallCard, { ToolCall } from '../components/chat/ToolCallCard'

interface ChatModelOption {
  providerId: string | null
  providerName: string
  modelName: string
}

export default function ChatPage() {
  const { convId } = useParams<{ convId?: string }>()
  const navigate = useNavigate()
  const { addToast } = useUIStore()

  const [conversations, setConversations] = useState<ConversationResponse[]>([])
  const [detail, setDetail] = useState<ConversationDetail | null>(null)
  const [options, setOptions] = useState<ChatModelOption[]>([])
  const [activeModel, setActiveModel] = useState<ChatModelOption>({
    providerId: null, providerName: 'Ollama', modelName: 'llava:7b',
  })

  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [streamContent, setStreamContent] = useState('')
  const [streamSources, setStreamSources] = useState<CitationSource[]>([])
  const [lastError, setLastError] = useState<string | null>(null)
  const [retryData, setRetryData] = useState<{ convId: string; text: string; model: ChatModelOption } | null>(null)
  const [modelSearch, setModelSearch] = useState('')
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false)
  const modelDropdownRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const uid = useAuthStore.getState().user?.id ?? 'anon'
  const lsKey = `agent-settings-${uid}`
  const [toolMode, setToolMode] = useState<'auto'|'none'>(
    () => (localStorage.getItem(lsKey+'.tm') as any) ?? 'auto')
  const [pluginMode, setPluginMode] = useState<'auto'|'none'>(
    () => (localStorage.getItem(lsKey+'.pm') as any) ?? 'auto')
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([])
  useEffect(() => {
    localStorage.setItem(lsKey+'.tm', toolMode)
    localStorage.setItem(lsKey+'.pm', pluginMode)
  }, [toolMode, pluginMode, lsKey])

  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const [searchQuery, setSearchQuery] = useState('')
  const [loadingConv, setLoadingConv] = useState(false)
  const latestFetchId = useRef<string | null>(null)
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null)

  useEffect(() => {
    chatApi.listConversations().then(setConversations).catch(() => {})
  }, [])

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
        // Prefer Ollama provider models (local LLM)
        if (!chosen) chosen = opts.find(o => o.providerName === 'Ollama')
        if (!chosen) chosen = opts[0]
        if (chosen) setActiveModel(chosen)
      } else {
        try {
          const ms = await import('../api/system').then(m => m.systemApi.listModels())
          // Find Ollama provider ID from the provider list
          const ollamaProvider = providerList.find(p => p.name === 'Ollama' || p.provider_type === 'ollama')
          const ollamaId = ollamaProvider?.id ?? null
          const legacy: ChatModelOption[] = ms.map(m => ({ providerId: ollamaId, providerName: 'Ollama', modelName: m.name }))
          setOptions(legacy)
          if (legacy.length > 0) setActiveModel(legacy.find(o => o.modelName === urlModel) ?? legacy[0])
        } catch { /* keep default */ }
      }
    })()
  }, [])

  useEffect(() => {
    if (convId) {
      latestFetchId.current = convId
      setLoadingConv(true)
      chatApi.getConversation(convId)
        .then((d) => {
          if (latestFetchId.current !== convId) return
          setDetail(d)
          setLoadingConv(false)
        })
        .catch(() => {
          if (latestFetchId.current !== convId) return
          setLoadingConv(false)
          navigate('/chat')
        })
    } else {
      setDetail(null)
      setLoadingConv(false)
    }
  }, [convId, conversations, navigate])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [detail?.messages, streamContent])

  useEffect(() => {
    return () => { abortRef.current?.abort() }
  }, [])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (modelDropdownRef.current && !modelDropdownRef.current.contains(e.target as Node)) {
        setModelDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const handleStop = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setStreaming(false)
    setStreamContent('')
    setStreamSources([])
    setToolCalls([])
  }, [])

  const doSend = useCallback(async (text: string, convIdParam: string | undefined, model: ChatModelOption, isRetry = false) => {
    if (!text.trim()) return
    const agentMode = toolMode !== 'none'

    setLastError(null)
    setStreaming(true)
    setStreamContent('')
    setStreamSources([])
    setToolCalls([])
    setRetryData(null)
    const controller = new AbortController()
    abortRef.current = controller

    try {
      let currentConvId = convIdParam
      if (!currentConvId) {
        const conv = await chatApi.createConversation({ model_name: model.modelName, title: text.slice(0, 80) })
        currentConvId = conv.id
        setConversations(prev => [conv, ...prev])
        navigate(`/chat/${conv.id}`, { replace: true })
      }
      prefsApi.set(model.providerId, model.modelName).catch(() => {})
      setDetail(prev => prev ? {...prev, messages: [...prev.messages, {
        id: 'tmp-'+Date.now(), role: 'user', content: text,
        token_count: null, finish_reason: null,
        created_at: new Date().toISOString()}]} : prev)

      const endpoint = agentMode
        ? `/api/v1/chat/conversations/${currentConvId}/agent`
        : `/api/v1/chat/conversations/${currentConvId}/messages`

      const body: Record<string, unknown> = {
        content: text, model_name: model.modelName, provider_id: model.providerId,
      }
      if (agentMode) {
        body.tool_mode = toolMode
        body.plugin_mode = pluginMode
      }

      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${useAuthStore.getState().accessToken}`,
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      })

      if (!resp.ok || !resp.body) throw new Error(`Stream failed (${resp.status})`)

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = '', acc = ''
      let evidenceReceived: CitationSource[] = []

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''

        let ev = ''
        for (const line of lines) {
          if (line.startsWith('event: ')) ev = line.slice(7).trim()
          else if (line.startsWith('data: ') && ev) {
            try {
              const d = JSON.parse(line.slice(6))
              if (ev === 'token') {
                acc += d.delta
                setStreamContent(acc)
              } else if (ev === 'evidence') {
                evidenceReceived = d.sources || []
                setStreamSources(evidenceReceived)
              } else if (ev === 'tool_call') {
                setToolCalls(prev => [...prev, {
                  call_id: d.call_id, tool: d.tool, status: 'running',
                  input_summary: d.input_summary, reasoning: d.reasoning,
                  timestamp: Date.now(),
                }])
              } else if (ev === 'tool_started') {
                setToolCalls(prev => prev.map(tc =>
                  tc.call_id === d.call_id ? {...tc, status: 'running'} : tc
                ))
              } else if (ev === 'tool_result') {
                setToolCalls(prev => prev.map(tc =>
                  tc.call_id === d.call_id ? {
                    ...tc, status: d.status === 'success' ? 'success' : 'error',
                    result_summary: d.result_summary, duration_ms: d.duration_ms,
                    error: d.error,
                  } : tc
                ))
              } else if (ev === 'tool_error') {
                setToolCalls(prev => prev.map(tc =>
                  tc.call_id === d.call_id ? {
                    ...tc, status: 'error', error: d.error,
                  } : tc
                ))
              } else if (ev === 'tool') {
                setToolCalls(prev => [...prev, {
                  call_id: d.call_id || `legacy-${Date.now()}`,
                  tool: d.tool, status: d.status === 'ok' ? 'success' : d.status === 'denied' ? 'denied' : d.status === 'approval_required' ? 'approval_required' : 'error',
                  result_summary: d.summary, duration_ms: d.ms, error: d.error,
                  timestamp: Date.now(),
                }])
              } else if (ev === 'plan') {
                // Plan event
              } else if (ev === 'error') {
                setLastError(d.message || 'Unknown error')
                addToast({ type: 'error', title: 'AI Error', message: d.message })
              }
            } catch { /* ignore parse errors */ }
            ev = ''
          }
        }
      }

      if (currentConvId) {
        const updated = await chatApi.getConversation(currentConvId)
        setDetail(updated)
        setConversations(prev => prev.map(c => c.id === currentConvId
          ? {...c, title: updated.title, message_count: updated.messages.length} : c))
      }
    } catch (err: any) {
      if (err?.name === 'AbortError') {
        setRetryData({ convId: convIdParam ?? '', text, model })
        return
      }
      setLastError(err?.message || 'Send failed')
      setRetryData({ convId: convIdParam ?? '', text, model })
      addToast({ type: 'error', title: 'Send failed', message: err?.message })
    } finally {
      setStreaming(false)
      setStreamContent('')
      setStreamSources([])
      abortRef.current = null
      inputRef.current?.focus()
    }
  }, [toolMode, pluginMode, navigate, addToast])

  const handleSend = useCallback(() => {
    const text = input.trim()
    if (!text || streaming) return
    setInput('')
    doSend(text, convId, activeModel)
  }, [input, streaming, convId, activeModel, doSend])

  const handleRetry = useCallback(() => {
    if (!retryData || streaming) return
    doSend(retryData.text, retryData.convId || convId, retryData.model, true)
  }, [retryData, streaming, convId, doSend])

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
      setConversations(prev => prev.map(c => c.id === id ? { ...c, title: newTitle.trim() } : c))
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
      setConversations(prev => prev.filter(c => c.id !== id))
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

  return (
    <div className="flex h-[calc(100vh-3.5rem-3rem)] gap-0">
      {/* Conversation list */}
      <aside className="w-64 flex-shrink-0 flex flex-col bg-[#0a1a0a] border-r border-green-900/30 rounded-l-lg overflow-hidden">
        <div className="p-3 space-y-2 border-b border-green-900/30">
          <button
            onClick={() => { navigate('/chat') }}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-green-600 text-white rounded-md text-sm font-medium hover:bg-green-500 transition-colors"
          >
            + New Chat
          </button>
          {conversations.length > 0 && (
            <input type="search" value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
              placeholder="Search conversations…" aria-label="Search conversations"
              className="w-full rounded-md border border-green-900/40 bg-[#050e05] px-2.5 py-1.5 text-xs text-neutral-200 placeholder-neutral-500 focus:outline-none focus:ring-1 focus:ring-green-500" />
          )}
        </div>
        <div className="flex-1 overflow-y-auto">
          {loadingConv ? (
            <div className="flex items-center justify-center py-8 gap-2 text-xs text-neutral-500">
              <span className="animate-spin h-3 w-3 border-2 border-green-900 border-t-green-400 rounded-full inline-block" />
              Loading…
            </div>
          ) : conversations.length === 0 ? (
            <p className="text-xs text-neutral-500 text-center mt-6 px-3">No conversations yet</p>
          ) : filtered.length === 0 ? (
            <p className="text-xs text-neutral-500 text-center mt-6 px-3">No matches for "{searchQuery}"</p>
          ) : (
            Object.entries(dateGroups).map(([group, items]) => (
              <div key={group}>
                <p className="px-3 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-green-700 select-none">{group}</p>
                {items.map(c => (
                  <div key={c.id}
                    className={`group relative flex items-center border-b border-green-900/20 transition-colors
                      ${convId === c.id ? 'bg-green-900/20 border-l-2 border-l-green-500' : 'hover:bg-green-900/10'}`}>
                    <button onClick={() => { navigate(`/chat/${c.id}`); setMenuOpenId(null) }}
                      className={`flex-1 text-left px-3 py-2 text-sm min-w-0 ${convId === c.id ? 'text-green-400' : 'text-neutral-300'}`}>
                      <div className="truncate font-medium">{c.title || 'New conversation'}</div>
                      <div className="text-[10px] text-neutral-500 mt-0.5 flex items-center gap-1">
                        <span>{timeAgo(c.updated_at)}</span>
                        <span>·</span>
                        <span className="truncate">{c.model_name}</span>
                      </div>
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); setMenuOpenId(menuOpenId === c.id ? null : c.id) }}
                      className="absolute right-1 top-1/2 -translate-y-1/2 p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-green-900/30 transition-opacity"
                      aria-label="Conversation options">
                      <span className="text-xs text-neutral-500">⋮</span>
                    </button>
                    {menuOpenId === c.id && (
                      <>
                        <div className="fixed inset-0 z-10" onClick={() => setMenuOpenId(null)} />
                        <div className="absolute right-2 top-full mt-0 z-20 w-32 bg-[#0a1a0a] rounded-md shadow-lg border border-green-900/40 py-1">
                          <button onClick={() => { setMenuOpenId(null); handleRename(c.id) }}
                            className="block w-full text-left px-3 py-1.5 text-xs text-neutral-300 hover:bg-green-900/20">
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
      <div className="flex flex-col flex-1 bg-[#050e05] rounded-r-lg overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center gap-3 px-4 py-2.5 bg-[#0a1a0a] border-b border-green-900/30 flex-shrink-0">
          <div className="relative" ref={modelDropdownRef}>
            <button
              onClick={() => { setModelDropdownOpen(v => !v); setModelSearch('') }}
              className="text-sm border border-green-900/40 rounded-md px-2 py-1 bg-[#050e05] text-neutral-200 focus:outline-none focus:ring-2 focus:ring-green-500 max-w-xs text-left flex items-center gap-1"
              aria-label="Select AI model"
            >
              <span className="truncate">{activeModel.providerName} / {activeModel.modelName}</span>
              <svg className="w-3 h-3 shrink-0 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
            </button>
            {modelDropdownOpen && (
              <div className="absolute z-50 mt-1 w-80 max-h-72 overflow-hidden bg-[#0a1a0a] border border-green-900/40 rounded-lg shadow-xl flex flex-col">
                <div className="p-2 border-b border-green-900/30">
                  <input
                    autoFocus
                    type="text"
                    placeholder="Search models..."
                    value={modelSearch}
                    onChange={e => setModelSearch(e.target.value)}
                    className="w-full text-sm px-2.5 py-1.5 rounded-md border border-green-900/40 bg-[#050e05] text-neutral-200 focus:outline-none focus:ring-1 focus:ring-green-500"
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
                        <div className="px-3 pt-2 pb-0.5 text-[10px] font-semibold uppercase tracking-wider text-green-700 select-none">{pname}</div>
                        {opts.map(o => (
                          <button
                            key={`${o.providerId}|${o.modelName}`}
                            onClick={() => {
                              setActiveModel(o)
                              prefsApi.set(o.providerId, o.modelName).catch(() => {})
                              setModelDropdownOpen(false)
                            }}
                            className={`w-full text-left px-3 py-1.5 text-sm hover:bg-green-900/20 transition-colors ${
                              o.providerId === activeModel.providerId && o.modelName === activeModel.modelName
                                ? 'bg-green-900/20 text-green-400 font-medium'
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
              : 'text-green-400 bg-green-900/20 border border-green-800/40'
          }`}>
            <span aria-hidden="true">{activeModel.providerId ? '☁️' : '🔒'}</span>
            {activeModel.providerId ? 'Cloud' : 'Local'}
          </span>
        </div>

        {/* Agent Settings */}
        <details className="w-full border-b border-green-900/30 bg-[#0a1a0a]/60">
          <summary className="cursor-pointer select-none px-4 py-1.5 text-xs font-medium text-green-700">
            ⚙️ Agent Settings {toolMode !== 'none' ? '(agent mode)' : '(direct chat)'}
          </summary>
          <div className="px-4 py-2 grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
            <div>
              <p className="font-medium mb-1 text-neutral-400">Tools</p>
              <select value={toolMode} onChange={e => setToolMode(e.target.value as any)}
                className="w-full rounded border border-green-900/40 bg-[#050e05] px-2 py-1 text-neutral-200"
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
        <div className="flex-1 overflow-y-auto px-4 py-4">
          {!convId && !streaming && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="text-4xl mb-3" aria-hidden="true">💬</div>
              <p className="text-neutral-400">Start a new conversation</p>
              <p className="text-xs text-neutral-500 mt-1">Press Ctrl+Enter to send</p>
            </div>
          )}

          {detail?.messages.map((m) => (
            <MessageBubble key={m.id} msg={m} />
          ))}

          {toolCalls.length > 0 && streaming && (
            <ToolCallCard calls={toolCalls} />
          )}

          {streaming && (
            <StreamingBubble
              content={streamContent}
              model={`${activeModel.providerName} / ${activeModel.modelName}`}
              sources={streamSources}
              onStop={handleStop}
            />
          )}

          {!streaming && detail?.messages.length && (() => {
            const lastAssistant = [...detail.messages].reverse().find(m => m.role === 'assistant')
            if (!lastAssistant?.metadata?.evidence?.sources) return null
            return (
              <EvidencePanel
                sources={lastAssistant.metadata.evidence.sources as CitationSource[]}
              />
            )
          })()}

          {lastError && !streaming && (
            <div className="mb-3 px-4 py-3 rounded-lg bg-red-900/20 border border-red-800/40 text-xs">
              <div className="flex items-start gap-2">
                <span className="text-red-400 mt-0.5">⚠</span>
                <div className="flex-1 min-w-0">
                  <p className="text-red-400 font-medium">AI Error</p>
                  <p className="text-red-300/80 mt-0.5 break-words">{lastError}</p>
                  <p className="text-neutral-500 mt-1">Model: {activeModel.modelName} · Provider: {activeModel.providerName}</p>
                </div>
                {retryData && (
                  <button onClick={handleRetry}
                    className="px-2 py-1 rounded bg-red-900/30 hover:bg-red-900/50 text-red-400 font-medium transition-colors flex-shrink-0">
                    ↻ Retry
                  </button>
                )}
                <button onClick={() => setLastError(null)}
                  className="px-1 text-neutral-500 hover:text-neutral-300 flex-shrink-0">✕</button>
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input bar */}
        <div className="px-4 py-3 bg-[#0a1a0a] border-t border-green-900/30 flex-shrink-0">
          {/* Model indicator */}
          <div className="flex items-center gap-2 mb-2 text-[10px] text-neutral-500">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
            <span>{activeModel.providerName}</span>
            <span>·</span>
            <span className="text-neutral-400">{activeModel.modelName}</span>
            {activeModel.providerId && <span className="text-green-600">(connected)</span>}
          </div>
          <div className="flex gap-2 items-end">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              placeholder="Type a message… (Ctrl+Enter to send)"
              disabled={streaming}
              className="flex-1 resize-none rounded-md border border-green-900/40 bg-[#050e05] px-3 py-2 text-sm text-neutral-200 placeholder-neutral-500 shadow-sm focus:outline-none focus:ring-2 focus:ring-green-500 disabled:opacity-50 max-h-40"
              aria-label="Chat message input"
            />
            {streaming ? (
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
                className="flex-shrink-0 bg-green-600 text-white rounded-md px-4 py-2 text-sm font-medium hover:bg-green-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
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
