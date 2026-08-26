import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { parseServerDate, istDateParts, nowISO } from '../utils/dates'
import { chatApi, ConversationDetail, ConversationResponse, MessageResponse } from '../api/chat'
import { providersApi, prefsApi, ModelRecord, ProviderResponse } from '../api/providers'
import { useAuthStore } from '../stores/authStore'
import { useUIStore } from '../stores/uiStore'

/** A selectable chat model: provider + model pair */
interface ChatModelOption {
  providerId: string | null
  providerName: string
  modelName: string
}

/* ---------- helpers ---------- */
function MessageBubble({ msg }: { msg: MessageResponse }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}>
      <div className={`max-w-[80%] px-4 py-3 rounded-2xl text-sm whitespace-pre-wrap
        ${isUser
          ? 'bg-primary-600 text-white rounded-tr-sm'
          : 'bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 text-neutral-800 dark:text-neutral-100 rounded-tl-sm'
        }`}>
        {msg.content}
      </div>
    </div>
  )
}

function StreamingBubble({ content, model }: { content: string; model: string }) {
  return (
    <div className="flex justify-start mb-3">
      <div className="max-w-[80%] px-4 py-3 rounded-2xl rounded-tl-sm bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 text-sm text-neutral-800 dark:text-neutral-100">
        <div className="text-xs text-neutral-400 mb-1 flex items-center gap-1">
          <span aria-hidden="true">⚡</span> {model}
        </div>
        {content ? content : <span className="streaming-cursor" />}
        {content && <span className="streaming-cursor" />}
      </div>
    </div>
  )
}

/* ---------- page ---------- */
export default function ChatPage() {
  const { convId } = useParams<{ convId?: string }>()
  const navigate = useNavigate()
  const { addToast } = useUIStore()

  const [conversations, setConversations] = useState<ConversationResponse[]>([])
  const [detail, setDetail] = useState<ConversationDetail | null>(null)
  // Grouped selectable models: enabled discovered models per provider
  const [options, setOptions] = useState<ChatModelOption[]>([])
  const [activeModel, setActiveModel] = useState<ChatModelOption>({
    providerId: null, providerName: 'Ollama', modelName: 'llama3.2:3b',
  })

  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [streamContent, setStreamContent] = useState('')

  // ---- Agent Settings (collapsible) ----
  const uid = useAuthStore.getState().user?.id ?? 'anon'
  const lsKey = `agent-settings-${uid}`
  const [showAgent, setShowAgent] = useState(false)
  const [toolMode, setToolMode] = useState<'auto'|'none'|'manual'>(
    () => (localStorage.getItem(lsKey+'.tm') as any) ?? 'auto')
  const [manualTools, setManualTools] = useState<string[]>(
    () => JSON.parse(localStorage.getItem(lsKey+'.mt') ?? '[]'))
  const [pluginMode, setPluginMode] = useState<'auto'|'none'>(
    () => (localStorage.getItem(lsKey+'.pm') as any) ?? 'auto')
  const [availTools, setAvailTools] = useState<{name:string;description:string}[]>([])
  const [activity, setActivity] = useState<{tool:string;status:string;summary?:string;ms?:number}[]>([])
  useEffect(() => {
    import('../api/tools').then(({toolsApi}) =>
      toolsApi.list().then(ts => setAvailTools(
        ts.filter(t=>t.enabled).map(t=>({name:t.name,description:t.description})))))
      .catch(()=>{})
  }, [])
  useEffect(() => {
    localStorage.setItem(lsKey+'.tm', toolMode)
    localStorage.setItem(lsKey+'.mt', JSON.stringify(manualTools))
    localStorage.setItem(lsKey+'.pm', pluginMode)
  }, [toolMode, manualTools, pluginMode, lsKey])

  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  // Set when the user explicitly starts a fresh chat — suppresses auto-restore
  const suppressRestore = useRef(false)

  // ---- Conversation management ----
  const [searchQuery, setSearchQuery] = useState('')
  const [loadingConv, setLoadingConv] = useState(false)
  const latestFetchId = useRef<string | null>(null)
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null)

  // Fetch conversation list from server (source of truth for sidebar + restore)
  useEffect(() => {
    chatApi.listConversations()
      .then(setConversations)
      .catch(() => {})
  }, [])

  /** Load providers → their catalogs → build grouped options; restore preference. */
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
      } catch { /* fall back to legacy local list below */ }

      const opts: ChatModelOption[] = modelRows.flatMap(({ provider, records }) =>
        records
          .filter(r => r.enabled && r.status === 'available')
          .map(r => ({
            providerId: provider.id,
            providerName: provider.name,
            modelName: r.model_id,
          })),
      )

      if (opts.length > 0) {
        setOptions(opts)
        let chosen: ChatModelOption | undefined
        // Priority: URL deep-link → saved user preference → first option
        if (urlModel) {
          chosen = opts.find(o =>
            o.modelName === urlModel && (!urlProvider || o.providerId === urlProvider))
        }
        if (!chosen) {
          try {
            const pref = await prefsApi.get()
            if (pref.model_name) {
              chosen = opts.find(o =>
                o.modelName === pref.model_name &&
                (pref.provider_id == null || o.providerId === pref.provider_id))
            }
          } catch { /* ignore */ }
        }
        if (chosen) setActiveModel(chosen)
      } else {
        // Legacy fallback: local Ollama role models
        try {
          const ms = await import('../api/system').then(m => m.systemApi.listModels())
          const legacy: ChatModelOption[] = ms.map(m => ({
            providerId: null, providerName: 'Ollama', modelName: m.name,
          }))
          setOptions(legacy)
          if (legacy.length > 0) {
            setActiveModel(legacy.find(o => o.modelName === urlModel) ?? legacy[0])
          }
        } catch { /* keep default */ }
      }
    })()
  }, [])

  // Load conversation detail when URL changes.
  // RESTORATION FIX: when landing on /chat with no convId (e.g. returning from
  // another page), restore the user's most recent conversation from the SERVER
  // list — never from local component memory.
  useEffect(() => {
    if (convId) {
      // Race-condition guard: track which convId we're fetching
      latestFetchId.current = convId
      setLoadingConv(true)
      chatApi.getConversation(convId)
        .then((d) => {
          // Only apply if this is still the active conversation
          if (latestFetchId.current !== convId) return
          setDetail(d)
          setLoadingConv(false)
          try { localStorage.setItem(`lastConv-${uid}`, d.id) } catch { /* ignore */ }
        })
        .catch(() => {
          if (latestFetchId.current !== convId) return
          setLoadingConv(false)
          navigate('/chat')
        })
    } else {
      setDetail(null)
      setLoadingConv(false)
      if (suppressRestore.current) return
      let stored: string | null = null
      try { stored = localStorage.getItem(`lastConv-${uid}`) } catch { /* ignore */ }
      if (conversations.length === 0) return
      const target =
        (stored && conversations.find(c => c.id === stored)) ||
        conversations[0]
      if (target) navigate(`/chat/${target.id}`, { replace: true })
    }
  }, [convId, conversations, navigate])

  // Scroll to bottom when messages update
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [detail?.messages, streamContent])

  const handleSend = async () => {
    const text = input.trim()
    if (!text || streaming) return
    const agentMode = toolMode !== 'none' || manualTools.length > 0

    // ---------- AGENT PATH (reuses backend planner + tool registry) ----------
    if (agentMode) {
      setInput(''); setStreaming(true); setStreamContent(''); setActivity([])
      try {
        let currentConvId = convId
        if (!currentConvId) {
          const conv = await chatApi.createConversation({
            model_name: activeModel.modelName, title: text.slice(0, 80)})
          currentConvId = conv.id
          setConversations(prev => [conv, ...prev])
          navigate(`/chat/${conv.id}`, { replace: true })
        }
        prefsApi.set(activeModel.providerId, activeModel.modelName).catch(() => {})
        setDetail(prev => prev ? {...prev, messages: [...prev.messages, {
          id: 'tmp-'+Date.now(), role: 'user', content: text,
          token_count: null, finish_reason: null,
          created_at: new Date().toISOString()}]} : prev)

        const resp = await fetch(`/api/v1/chat/conversations/${currentConvId}/agent`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json',
                    Authorization: `Bearer ${useAuthStore.getState().accessToken}`},
          body: JSON.stringify({
            content: text, model_name: activeModel.modelName,
            provider_id: activeModel.providerId,
            tool_mode: toolMode, tools: manualTools, plugin_mode: pluginMode,
          }),
        })
        if (!resp.ok || !resp.body) throw new Error(`Agent failed (${resp.status})`)
        const reader = resp.body.getReader(); const dec = new TextDecoder()
        let buf = '', acc = ''
        while (true) {
          const {done, value} = await reader.read(); if (done) break
          buf += dec.decode(value, {stream: true})
          const lines = buf.split('\n'); buf = lines.pop() ?? ''
          let ev = ''
          for (const line of lines) {
            if (line.startsWith('event: ')) ev = line.slice(7).trim()
            else if (line.startsWith('data: ') && ev) {
              try {
                const d = JSON.parse(line.slice(6))
                if (ev === 'token') { acc += d.delta; setStreamContent(acc) }
                else if (ev === 'tool') setActivity(a => [...a, d])
                else if (ev === 'plan') setActivity(a => [...a, {
                  tool: `plan:${d.task_type}`, status: 'ok',
                  summary: `${d.tools.length ? d.tools.join(', ') : 'no tools'}`}])
                else if (d.code) addToast({type:'error',title:'Agent error',message:d.message})
              } catch {/* ignore */}
              ev = ''
            }
          }
        }
        if (currentConvId) {
          const upd = await chatApi.getConversation(currentConvId)
          setDetail(upd)
          setConversations(prev => prev.map(c => c.id === currentConvId
            ? {...c, title: upd.title, message_count: upd.messages.length} : c))
        }
      } catch (err: any) {
        addToast({type:'error',title:'Send failed',message: err?.message})
      } finally {
        setStreaming(false); setStreamContent(''); inputRef.current?.focus()
      }
      return
    }

    // ---------- DIRECT CHAT PATH (unchanged) ----------
    setInput('')
    setStreaming(true)
    setStreamContent('')

    try {
      let currentConvId = convId

      // Create conversation if needed (legacy model_name kept for display)
      if (!currentConvId) {
        const conv = await chatApi.createConversation({
          model_name: activeModel.modelName, title: text.slice(0, 80),
        })
        currentConvId = conv.id
        setConversations((prev) => [conv, ...prev])
        navigate(`/chat/${conv.id}`, { replace: true })
      }

      // Persist this selection as the user's preferred model
      prefsApi.set(activeModel.providerId, activeModel.modelName).catch(() => {})

      // Optimistically add user message to view
      setDetail((prev) => {
        if (!prev) return prev
        const fake: MessageResponse = {
          id: 'tmp-' + Date.now(),
          role: 'user', content: text,
          token_count: null, finish_reason: null,
          created_at: new Date().toISOString(),
        }
        return { ...prev, messages: [...prev.messages, fake] }
      })

      // Open SSE stream — provider_id routes to the selected provider's connection
      const resp = await fetch(`/api/v1/chat/conversations/${currentConvId}/messages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${useAuthStore.getState().accessToken}`,
        },
        body: JSON.stringify({
          content: text,
          model_name: activeModel.modelName,
          provider_id: activeModel.providerId,
        }),
      })

      if (!resp.ok || !resp.body) {
        throw new Error('Stream failed')
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      let accumulated = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              if (data.delta) {
                accumulated += data.delta
                setStreamContent(accumulated)
              }
              if (data.code) {
                addToast({ type: 'error', title: 'AI Error', message: data.message })
              }
            } catch { /* ignore parse errors */ }
          }
        }
      }

      // Reload conversation to get saved assistant message
      if (currentConvId) {
        const updated = await chatApi.getConversation(currentConvId)
        setDetail(updated)
        // Update sidebar
        setConversations((prev) =>
          prev.map((c) => c.id === currentConvId ? { ...c, title: updated.title, message_count: updated.messages.length } : c)
        )
      }
    } catch (err: any) {
      addToast({ type: 'error', title: 'Send failed', message: err?.message })
    } finally {
      setStreaming(false)
      setStreamContent('')
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      handleSend()
    }
  }

  // ---- Conversation management handlers ----
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
      try {
        if (localStorage.getItem(`lastConv-${uid}`) === id) localStorage.removeItem(`lastConv-${uid}`)
      } catch { /* ignore */ }
      addToast({ type: 'info', title: 'Conversation deleted' })
    } catch {
      addToast({ type: 'error', title: 'Delete failed' })
    }
  }

  const filtered = useMemo(() =>
    conversations.filter(c =>
      !searchQuery || (c.title ?? '').toLowerCase().includes(searchQuery.toLowerCase())
    ), [conversations, searchQuery])

  const dateGroups = useMemo(() => {
    const groups: Record<string, ConversationResponse[]> = {}
    // Get "today" in IST for correct grouping
    const nowIST = istDateParts(new Date())
    const yesterdayIST = { ...nowIST }
    // Decrement day safely
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
  }, [filtered])

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
      {/* ---- Conversation list ---- */}
      <aside className="w-64 flex-shrink-0 flex flex-col bg-white dark:bg-neutral-800 border-r border-neutral-200 dark:border-neutral-700 rounded-l-lg overflow-hidden">
        <div className="p-3 space-y-2 border-b border-neutral-200 dark:border-neutral-700">
          <button
            onClick={() => { suppressRestore.current = true; navigate('/chat') }}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700 transition-colors"
          >
            + New Chat
          </button>
          {conversations.length > 0 && (
            <input type="search" value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
              placeholder="Search conversations…" aria-label="Search conversations"
              className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-neutral-50 dark:bg-neutral-700 px-2.5 py-1.5 text-xs text-neutral-800 dark:text-neutral-100 placeholder-neutral-400 focus:outline-none focus:ring-1 focus:ring-primary-400" />
          )}
        </div>
        <div className="flex-1 overflow-y-auto">
          {loadingConv ? (
            <div className="flex items-center justify-center py-8 gap-2 text-xs text-neutral-400">
              <span className="animate-spin h-3 w-3 border-2 border-neutral-300 border-t-primary-500 rounded-full inline-block" />
              Loading conversation…
            </div>
          ) : conversations.length === 0 ? (
            <p className="text-xs text-neutral-400 text-center mt-6 px-3">No conversations yet</p>
          ) : filtered.length === 0 ? (
            <p className="text-xs text-neutral-400 text-center mt-6 px-3">No matches for "{searchQuery}"</p>
          ) : (
            Object.entries(dateGroups).map(([group, items]) => (
              <div key={group}>
                <p className="px-3 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-neutral-400 select-none">{group}</p>
                {items.map(c => (
                  <div key={c.id}
                    className={`group relative flex items-center border-b border-neutral-100 dark:border-neutral-700 transition-colors
                      ${convId === c.id ? 'bg-primary-50 dark:bg-primary-900/20' : 'hover:bg-neutral-50 dark:hover:bg-neutral-700/50'}`}>
                    <button onClick={() => { navigate(`/chat/${c.id}`); setMenuOpenId(null) }}
                      className={`flex-1 text-left px-3 py-2 text-sm min-w-0 ${convId === c.id ? 'text-primary-700 dark:text-primary-300' : 'text-neutral-700 dark:text-neutral-300'}`}>
                      <div className="truncate font-medium">{c.title || 'New conversation'}</div>
                      <div className="text-[10px] text-neutral-400 mt-0.5 flex items-center gap-1">
                        <span>{timeAgo(c.updated_at)}</span>
                        <span>·</span>
                        <span className="truncate">{c.model_name}</span>
                      </div>
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); setMenuOpenId(menuOpenId === c.id ? null : c.id) }}
                      className="absolute right-1 top-1/2 -translate-y-1/2 p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-neutral-200 dark:hover:bg-neutral-600 transition-opacity"
                      aria-label="Conversation options">
                      <span className="text-xs text-neutral-500">⋮</span>
                    </button>
                    {menuOpenId === c.id && (
                      <>
                        <div className="fixed inset-0 z-10" onClick={() => setMenuOpenId(null)} />
                        <div className="absolute right-2 top-full mt-0 z-20 w-32 bg-white dark:bg-neutral-700 rounded-md shadow-lg border border-neutral-200 dark:border-neutral-600 py-1">
                          <button onClick={() => { setMenuOpenId(null); handleRename(c.id) }}
                            className="block w-full text-left px-3 py-1.5 text-xs text-neutral-700 dark:text-neutral-200 hover:bg-neutral-50 dark:hover:bg-neutral-600">
                            ✎ Rename
                          </button>
                          <button onClick={() => { setMenuOpenId(null); handleDelete(c.id) }}
                            className="block w-full text-left px-3 py-1.5 text-xs text-danger-600 hover:bg-danger-50 dark:hover:bg-danger-900/30">
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

      {/* ---- Chat area ---- */}
      <div className="flex flex-col flex-1 bg-neutral-50 dark:bg-neutral-900 rounded-r-lg overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center gap-3 px-4 py-2.5 bg-white dark:bg-neutral-800 border-b border-neutral-200 dark:border-neutral-700 flex-shrink-0">
          {/* Grouped model selector: models grouped under their provider */}
          <select
            value={`${activeModel.providerId ?? ''}|${activeModel.modelName}`}
            onChange={(e) => {
              const [pid, model] = e.target.value.split('|')
              const opt = options.find(
                o => (o.providerId ?? '') === pid && o.modelName === model)
              if (opt) {
                setActiveModel(opt)
                prefsApi.set(opt.providerId, opt.modelName).catch(() => {})
              }
            }}
            className="text-sm border border-neutral-300 dark:border-neutral-600 rounded-md px-2 py-1 bg-white dark:bg-neutral-700 text-neutral-800 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-primary-500 max-w-xs"
            aria-label="Select AI model"
          >
            {options.length === 0 ? (
              <option value={`${activeModel.providerId ?? ''}|${activeModel.modelName}`}>
                {activeModel.providerName} / {activeModel.modelName}
              </option>
            ) : (
              /* group by provider name, preserving provider order */
              Object.entries(
                options.reduce<Record<string, ChatModelOption[]>>((acc, o) => {
                  (acc[o.providerName] = acc[o.providerName] || []).push(o)
                  return acc
                }, {}),
              ).map(([pname, opts]) => (
                <optgroup key={pname} label={pname}>
                  {opts.map(o => (
                    <option key={`${o.providerId}|${o.modelName}`}
                      value={`${o.providerId ?? ''}|${o.modelName}`}>
                      {o.modelName}
                    </option>
                  ))}
                </optgroup>
              ))
            )}
          </select>
          <span className="text-xs text-neutral-400 truncate max-w-40">{activeModel.providerName}</span>
          <span className={`text-xs rounded px-2 py-0.5 flex items-center gap-1 ${
            activeModel.providerId
              ? 'text-blue-700 bg-blue-50 border border-blue-200'
              : 'text-success-700 bg-success-50 border border-success-200'
          }`}>
            <span aria-hidden="true">{activeModel.providerId ? '☁️' : '🔒'}</span>
            {activeModel.providerId ? 'Cloud/Remote' : 'Local'}
          </span>
        </div>

        {/* Agent Settings — collapsible, compact by default */}
        <details className="w-full border-b border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/60">
          <summary className="cursor-pointer select-none px-4 py-1.5 text-xs font-medium text-neutral-500 dark:text-neutral-400">
            ⚙️ Agent Settings {toolMode !== 'none' || manualTools.length > 0 ? '(agent mode)' : '(direct chat)'}
          </summary>
          <div className="px-4 py-2 grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
            <div>
              <p className="font-medium mb-1 text-neutral-600 dark:text-neutral-300">Tools</p>
              <select value={toolMode} onChange={e => setToolMode(e.target.value as any)}
                className="w-full rounded border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-2 py-1 text-neutral-800 dark:text-neutral-100"
                aria-label="Tools mode">
                <option value="auto">Auto (planner picks)</option>
                <option value="none">None</option>
                <option value="manual" disabled={availTools.length===0}>Select manually…</option>
              </select>
              {toolMode==='manual' && (
                <div className="mt-1 max-h-32 overflow-y-auto rounded border border-neutral-200 dark:border-neutral-700 p-1 space-y-0.5">
                  {availTools.map(t => (
                    <label key={t.name} className="flex items-center gap-1.5 cursor-pointer">
                      <input type="checkbox" checked={manualTools.includes(t.name)}
                        onChange={e => setManualTools(m =>
                          e.target.checked ? [...m, t.name] : m.filter(x=>x!==t.name))}/>
                      <span className="truncate">{t.name}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
            <div>
              <p className="font-medium mb-1 text-neutral-600 dark:text-neutral-300">Plugins</p>
              <select value={pluginMode} onChange={e => setPluginMode(e.target.value as any)}
                className="w-full rounded border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-2 py-1 text-neutral-800 dark:text-neutral-100"
                aria-label="Plugins mode">
                <option value="auto">Auto</option>
                <option value="none">None</option>
              </select>
              <p className="text-[10px] text-neutral-400 mt-1">Plugin gating is enforced server-side.</p>
            </div>
            <div>
              <p className="font-medium mb-1 text-neutral-600 dark:text-neutral-300">Model</p>
              <p className="text-[11px] text-neutral-500 truncate">
                {activeModel.providerName} / {activeModel.modelName}
              </p>
              <p className="text-[10px] text-neutral-400 mt-1">Change via the selector above; Auto tools still respect it.</p>
            </div>
          </div>
        </details>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4">
          {!convId && !streaming && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="text-4xl mb-3" aria-hidden="true">💬</div>
              <p className="text-neutral-500 dark:text-neutral-400">Start a new conversation</p>
              <p className="text-xs text-neutral-400 mt-1">Press Ctrl+Enter to send</p>
            </div>
          )}

          {detail?.messages.map((m) => <MessageBubble key={m.id} msg={m} />)}
          {activity.length > 0 && streaming && (
            <details open className="flex justify-start mb-3">
              <summary className="text-xs text-neutral-400 cursor-pointer">Agent activity</summary>
              <div className="ml-2 mt-1 text-xs text-neutral-500 space-y-0.5">
                {activity.map((a, i) => (
                  <div key={i}>
                    {a.status === 'ok' ? '✓' : a.status === 'approval_required' ? '⚠️' : '•'}{' '}
                    {a.tool}{a.summary ? ` — ${a.summary}` : ''}
                    {a.ms != null ? ` (${a.ms}ms)` : ''}
                  </div>
                ))}
              </div>
            </details>
          )}
          {streaming && <StreamingBubble content={streamContent} model={`${activeModel.providerName} / ${activeModel.modelName}`} />}
          <div ref={bottomRef} />
        </div>

        {/* Input bar */}
        <div className="px-4 py-3 bg-white dark:bg-neutral-800 border-t border-neutral-200 dark:border-neutral-700 flex-shrink-0">
          <div className="flex gap-2 items-end">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              placeholder="Type a message… (Ctrl+Enter to send)"
              disabled={streaming}
              className="flex-1 resize-none rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 placeholder-neutral-400 shadow-sm focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50 max-h-40"
              aria-label="Chat message input"
            />
            <button
              onClick={handleSend}
              disabled={streaming || !input.trim()}
              className="flex-shrink-0 bg-primary-600 text-white rounded-md px-4 py-2 text-sm font-medium hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              aria-label="Send message"
            >
              {streaming ? (
                <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full inline-block" aria-hidden="true" />
              ) : 'Send'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
