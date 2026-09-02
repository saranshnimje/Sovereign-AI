import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  providersApi, prefsApi,
  ModelRecord, ProviderResponse, ProviderTestResult, ProviderUpdate,
} from '../api/providers'
import { systemApi, ModelInfo } from '../api/system'
import { API_BASE } from '../api/client'
import { useAuthStore } from '../stores/authStore'
import { useUIStore } from '../stores/uiStore'

function formatSize(bytes?: number | null): string {
  if (!bytes) return ''
  if (bytes > 1e9) return `${(bytes / 1e9).toFixed(1)} GB`
  return `${(bytes / 1e6).toFixed(0)} MB`
}

function ModelCard({ record, isAdmin, onToggle, isRunning }: {
  record: ModelRecord; isAdmin: boolean; onToggle: (r: ModelRecord) => void; isRunning: boolean
}) {
  const navigate = useNavigate()
  const { addToast } = useUIStore()
  const [testing, setTesting] = useState(false)

  const meta = [
    record.family, record.parameter_size, formatSize(record.size_bytes),
    record.quantization, record.context_length ? `${record.context_length.toLocaleString()} ctx` : null,
  ].filter(Boolean) as string[]

  const unavailable = record.status !== 'available'

  const handleTest = async () => {
    setTesting(true)
    try {
      const h = await systemApi.modelHealth(record.model_id)
      addToast({
        type: h.status === 'available' ? 'success' : 'error',
        title: `${record.model_id}: ${h.status}`,
        message: h.latency_ms != null ? `${h.latency_ms}ms` : '',
      })
    } catch { addToast({ type: 'error', title: 'Test failed' }) }
    finally { setTesting(false) }
  }

  return (
    <div className={`bg-surface-raised border rounded-xl p-4 transition-all
      ${unavailable ? 'opacity-50 border-surface-border'
        : record.enabled ? 'border-surface-border'
        : 'border-dashed border-surface-border'}`}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-mono text-sm font-semibold text-neutral-100 truncate" title={record.model_id}>
              {record.model_id}
            </h3>
            {isRunning && (
              <span className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/30">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-cyan-500" />
                </span>
                Running
              </span>
            )}
          </div>
          {meta.length > 0 && <p className="text-xs text-neutral-500 mt-0.5">{meta.join(' · ')}</p>}
          {record.size_bytes && (
            <p className="text-[10px] text-neutral-600 mt-0.5">Downloaded: {formatSize(record.size_bytes)}</p>
          )}
        </div>
        <div className="flex flex-col gap-1 items-end flex-shrink-0">
          <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
            unavailable ? 'bg-neutral-800 text-neutral-500' : 'bg-cyan-500/10 text-cyan-400'}`}>
            {unavailable ? 'unavailable' : 'available'}
          </span>
          {!record.enabled && !unavailable && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-yellow-900/20 text-yellow-400">disabled</span>
          )}
        </div>
      </div>
      {isAdmin && (
        <div className="flex gap-1.5 flex-wrap mt-2">
          <button onClick={() => onToggle(record)} disabled={unavailable}
            className={`text-xs px-2 py-1 rounded border transition-colors disabled:opacity-40 ${
              record.enabled
                ? 'bg-cyan-600 text-white border-cyan-600 hover:bg-cyan-500'
                : 'border-surface-border text-neutral-300 hover:bg-surface-muted'
            }`}>
            {record.enabled ? '✓ Enabled' : 'Enable'}
          </button>
          {record.enabled && (
            <>
              <button onClick={handleTest} disabled={testing}
                className="text-xs px-2 py-1 rounded border border-surface-border text-neutral-300 hover:bg-surface-muted disabled:opacity-40">
                {testing ? '…' : 'Test'}
              </button>
              <button onClick={() => navigate(`/chat?model=${encodeURIComponent(record.model_id)}&provider=${record.provider_id}`)}
                disabled={unavailable}
                className="text-xs px-2 py-1 rounded border border-cyan-600/50 text-cyan-400 hover:bg-surface-muted disabled:opacity-40">
                💬 Chat
              </button>
            </>
          )}
          {!record.enabled && (
            <button onClick={() => onToggle(record)}
              className="text-xs px-2 py-1 rounded border border-surface-border text-neutral-400 hover:bg-surface-muted">
              Enable to chat
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function ProviderSettingsModal({ provider, onClose, onSave }: {
  provider: ProviderResponse; onClose: () => void; onSave: (data: ProviderUpdate) => Promise<void>
}) {
  const [name, setName] = useState(provider.name)
  const [baseUrl, setBaseUrl] = useState(provider.base_url || '')
  const [supportsEmbed, setSupportsEmbed] = useState(provider.supports_embeddings)
  const [enabled, setEnabled] = useState(provider.enabled)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      await onSave({ name, base_url: baseUrl, supports_embeddings: supportsEmbed, enabled })
      onClose()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to save')
    } finally {
      setLoading(false)
    }
  }

  const inputCls = "w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:ring-2 focus:ring-cyan-500"

  return (
    <div className="fixed inset-0 bg-black/60 z-40 flex items-center justify-center p-4">
      <div className="bg-surface-raised border border-surface-border rounded-xl shadow-xl w-full max-w-lg" role="dialog" aria-modal="true">
        <div className="flex items-center justify-between p-6 border-b border-surface-border">
          <h2 className="text-lg font-semibold text-white">Provider Settings</h2>
          <button onClick={onClose} className="text-neutral-500 hover:text-neutral-300">✕</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="p-6 space-y-4">
            {error && <div className="p-3 bg-red-900/20 border border-red-800/40 rounded-lg text-sm text-red-400">{error}</div>}
            <div>
              <label className="block text-sm font-medium text-neutral-300 mb-1">Display Name</label>
              <input type="text" value={name} onChange={e => setName(e.target.value)} required className={inputCls} />
            </div>
            <div>
              <label className="block text-sm font-medium text-neutral-300 mb-1">Base URL</label>
              <input type="url" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} className={inputCls + ' font-mono'} />
            </div>
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 cursor-pointer text-sm text-neutral-300">
                <input type="checkbox" checked={supportsEmbed} onChange={e => setSupportsEmbed(e.target.checked)} className="h-4 w-4 rounded border-surface-border text-cyan-500 focus:ring-cyan-500" />
                Supports embeddings
              </label>
              <label className="flex items-center gap-2 cursor-pointer text-sm text-neutral-300">
                <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} className="h-4 w-4 rounded border-surface-border text-cyan-500 focus:ring-cyan-500" />
                Enabled
              </label>
            </div>
          </div>
          <div className="flex justify-end gap-3 p-6 border-t border-surface-border">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm font-medium text-neutral-300 border border-surface-border rounded-lg hover:bg-surface-muted">Cancel</button>
            <button type="submit" disabled={loading || !name.trim()} className="px-4 py-2 text-sm font-medium text-white bg-cyan-600 rounded-lg hover:bg-cyan-500 disabled:opacity-50">
              {loading ? 'Saving…' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function ModelsPage() {
  const { user } = useAuthStore()
  const { addToast } = useUIStore()
  const isAdmin = user?.role === 'admin'
  const navigate = useNavigate()

  const [providers, setProviders] = useState<ProviderResponse[]>([])
  const [catalog, setCatalog] = useState<Record<string, ModelRecord[]>>({})
  const [loading, setLoading] = useState(true)
  const [refreshingId, setRefreshingId] = useState<string | null>(null)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{ name: string; result: ProviderTestResult } | null>(null)
  const [runningModels, setRunningModels] = useState<Set<string>>(new Set())
  const [editingProvider, setEditingProvider] = useState<ProviderResponse | null>(null)

  const [search, setSearch] = useState('')
  const [providerFilter, setProviderFilter] = useState<string>('all')
  const [statusFilter, setStatusFilter] = useState<'all' | 'enabled' | 'disabled'>('all')
  const [sortAsc, setSortAsc] = useState(true)

  const [pullName, setPullName] = useState('')
  const [pulling, setPulling] = useState(false)
  const [pullLog, setPullLog] = useState<string[]>([])
  const [collapsedProviders, setCollapsedProviders] = useState<Set<string>>(new Set())
  const pullLogRef = useRef<HTMLDivElement>(null)

  const loadAll = useCallback(async () => {
    try {
      const [ps, status] = await Promise.allSettled([providersApi.list(), systemApi.status()])
      if (ps.status === 'fulfilled') {
        setProviders(ps.value)
        const results = await Promise.allSettled(ps.value.map(p => providersApi.getModels(p.id)))
        const next: Record<string, ModelRecord[]> = {}
        ps.value.forEach((p, i) => { next[p.id] = results[i].status === 'fulfilled' ? results[i].value : [] })
        setCatalog(next)
      }
      if (status.status === 'fulfilled') {
        const loaded = new Set(status.value.models_loaded || [])
        setRunningModels(loaded)
      }
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])
  useEffect(() => { if (pullLogRef.current) pullLogRef.current.scrollTop = pullLogRef.current.scrollHeight }, [pullLog])

  const handleRefresh = async (p: ProviderResponse) => {
    setRefreshingId(p.id)
    try {
      const rows = await providersApi.refreshModels(p.id)
      setCatalog(prev => ({ ...prev, [p.id]: rows }))
      addToast({ type: 'success', title: `Refreshed ${p.name}`, message: `${rows.filter(m => m.status === 'available').length} models available` })
    } catch (err: any) {
      addToast({ type: 'error', title: `Could not refresh ${p.name}`, message: err?.response?.data?.detail || 'Provider unreachable' })
    } finally { setRefreshingId(null) }
  }

  const handleRefreshAll = async () => { for (const p of providers.filter(x => x.enabled)) await handleRefresh(p) }

  const handleTestProvider = async (p: ProviderResponse) => {
    if (!isAdmin) return
    setTestingId(p.id)
    try { const result = await providersApi.test(p.id); setTestResult({ name: p.name, result }) }
    catch { addToast({ type: 'error', title: 'Test failed' }) }
    finally { setTestingId(null) }
  }

  const handleToggle = async (providerId: string, r: ModelRecord) => {
    try {
      const updated = await providersApi.setModelEnabled(providerId, r.id, !r.enabled)
      setCatalog(prev => ({ ...prev, [providerId]: (prev[providerId] || []).map(m => m.id === updated.id ? updated : m) }))
      addToast({ type: 'success', title: `${updated.model_id} ${updated.enabled ? 'enabled' : 'disabled'}` })
    } catch { addToast({ type: 'error', title: 'Failed to update model' }) }
  }

  const handleUpdateProvider = async (data: ProviderUpdate) => {
    if (!editingProvider) return
    const updated = await providersApi.update(editingProvider.id, data)
    setProviders(prev => prev.map(p => p.id === updated.id ? updated : p))
    addToast({ type: 'success', title: 'Provider updated' })
  }

  const handlePull = async () => {
    const name = pullName.trim()
    if (!name) return
    setPulling(true); setPullLog([`Starting pull: ${name}`])
    try {
      const resp = await fetch(`${API_BASE}/api/v1/models/pull`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${useAuthStore.getState().accessToken}` },
        body: JSON.stringify({ model_name: name }),
      })
      if (!resp.ok || !resp.body) { setPullLog(prev => [...prev, `Error: HTTP ${resp.status}`]); return }
      const reader = resp.body.getReader(); const decoder = new TextDecoder(); let buf = ''
      while (true) {
        const { done, value } = await reader.read(); if (done) break
        buf += decoder.decode(value, { stream: true }); const lines = buf.split('\n'); buf = lines.pop() ?? ''
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try { const data = JSON.parse(line.slice(6)); const msg = data.status || data.message; if (msg) setPullLog(prev => [...prev.slice(-50), msg]) } catch {}
          }
        }
      }
      setPullLog(prev => [...prev, `✓ Pulled ${name}`]); setPullName('')
    } catch (err: any) { setPullLog(prev => [...prev, `Error: ${err.message}`]) }
    finally { setPulling(false) }
  }

  const filteredProviders = useMemo(() =>
    providerFilter === 'all' ? providers : providers.filter(p => p.id === providerFilter), [providers, providerFilter])

  const matchesFilters = (m: ModelRecord) => {
    if (search && !m.model_id.toLowerCase().includes(search.toLowerCase())) return false
    if (statusFilter === 'enabled' && !(m.enabled && m.status === 'available')) return false
    if (statusFilter === 'disabled' && (m.enabled && m.status === 'available')) return false
    return true
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Models</h1>
          <p className="text-sm text-neutral-400 mt-1">Discovered from your providers — grouped by connection</p>
        </div>
        <button onClick={handleRefreshAll} disabled={refreshingId !== null || providers.length === 0}
          className="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-medium hover:bg-cyan-500 disabled:opacity-50 transition-colors">
          {refreshingId ? '⟳ Refreshing…' : '↻ Refresh All'}
        </button>
      </div>

      {testResult && (
        <div className={`p-3 rounded-lg border text-sm flex items-center justify-between ${
          testResult.result.success ? 'bg-cyan-500/10 border-surface-border text-cyan-400' : 'bg-red-900/20 border-red-800/40 text-red-400'}`}>
          <span>{testResult.result.success
            ? `✓ ${testResult.name} connected — ${testResult.result.models_found ?? '?'} models (${testResult.result.latency_ms}ms)`
            : `✗ ${testResult.name}: ${testResult.result.error || 'Connection failed'}`}</span>
          <button onClick={() => setTestResult(null)} className="opacity-60 hover:opacity-100 ml-2">✕</button>
        </div>
      )}

      <div className="flex gap-3 flex-wrap items-center">
        <input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search models…"
          className="flex-1 min-w-48 rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-sm text-neutral-200 placeholder-neutral-500 focus:outline-none focus:ring-2 focus:ring-cyan-500" />
        <select value={providerFilter} onChange={e => setProviderFilter(e.target.value)}
          className="rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-sm text-neutral-200">
          <option value="all">All Providers</option>
          {providers.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value as any)}
          className="rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-sm text-neutral-200">
          <option value="all">All Status</option>
          <option value="enabled">Enabled</option>
          <option value="disabled">Disabled / Unavailable</option>
        </select>
        <button onClick={() => setSortAsc(a => !a)} className="text-sm text-cyan-400 hover:text-cyan-300 whitespace-nowrap">
          Sort {sortAsc ? 'A→Z' : 'Z→A'}
        </button>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => <div key={i} className="bg-surface-raised border border-surface-border rounded-xl h-32 animate-pulse" />)}
        </div>
      ) : providers.length === 0 ? (
        <div className="flex flex-col items-center justify-center min-h-48 text-center">
          <div className="text-4xl mb-3">🔌</div>
          <p className="text-neutral-400 font-medium">No providers configured yet</p>
          <p className="text-xs text-neutral-500 mt-1">Add a provider to discover available models</p>
          {isAdmin && (
            <button onClick={() => navigate('/providers')}
              className="mt-3 px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-medium hover:bg-cyan-500">
              + Add a Provider first
            </button>
          )}
        </div>
      ) : (
        filteredProviders.map(p => {
          const rows = (catalog[p.id] ?? []).filter(matchesFilters)
            .sort((a, b) => sortAsc ? a.model_id.localeCompare(b.model_id) : b.model_id.localeCompare(a.model_id))
          const availableCount = (catalog[p.id] ?? []).filter(m => m.enabled && m.status === 'available').length
          return (
            <section key={p.id}>
              <div className="flex items-center justify-between flex-wrap gap-2 mb-3 pb-2 border-b border-surface-border">
                <div className="flex items-center gap-2 flex-wrap">
                  <button onClick={() => setCollapsedProviders(prev => { const next = new Set(prev); if (next.has(p.id)) next.delete(p.id); else next.add(p.id); return next })}
                    className="text-neutral-500 hover:text-neutral-300 transition-colors p-0.5"
                    aria-label={collapsedProviders.has(p.id) ? 'Expand' : 'Collapse'}>
                    <svg className={`w-4 h-4 transition-transform ${collapsedProviders.has(p.id) ? '-rotate-90' : ''}`}
                      fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>
                  <h2 className="text-base font-bold text-white">{p.name}</h2>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    p.enabled ? 'bg-cyan-500/10 text-cyan-400' : 'bg-neutral-800 text-neutral-500'}`}>
                    {p.enabled ? `✓ ${availableCount} available` : 'disabled'}
                  </span>
                  <span className="text-xs text-neutral-500 font-mono">{p.base_url}</span>
                </div>
                  <div className="flex gap-1.5">
                    <button onClick={() => handleRefresh(p)} disabled={refreshingId === p.id}
                      className="text-xs px-2.5 py-1.5 border border-surface-border text-neutral-300 rounded-lg hover:bg-surface-muted disabled:opacity-50">
                      {refreshingId === p.id ? '⟳ Discovering…' : '↻ Refresh'}
                    </button>
                    {isAdmin && (
                      <>
                        <button onClick={() => handleTestProvider(p)} disabled={testingId === p.id}
                          className="text-xs px-2.5 py-1.5 border border-surface-border text-neutral-300 rounded-lg hover:bg-surface-muted disabled:opacity-50">
                          {testingId === p.id ? 'Testing…' : '⚡ Test'}
                        </button>
                        <button onClick={() => setEditingProvider(p)}
                          className="text-xs px-2.5 py-1.5 border border-surface-border text-neutral-300 rounded-lg hover:bg-surface-muted">
                          ⚙ Settings
                        </button>
                      </>
                    )}
                  </div>
              </div>
              {!collapsedProviders.has(p.id) && (
                rows.length === 0 ? (
                  (catalog[p.id] ?? []).length === 0 ? (
                    <div className="text-center py-8 bg-surface-raised rounded-xl border border-dashed border-surface-border">
                      <p className="text-sm text-neutral-500">No models discovered yet.</p>
                      <button onClick={() => handleRefresh(p)} disabled={refreshingId === p.id}
                        className="mt-2 text-sm text-cyan-400 hover:text-cyan-300">
                        {refreshingId === p.id ? 'Discovering…' : 'Refresh Models now →'}
                      </button>
                    </div>
                  ) : <p className="text-center py-6 text-sm text-neutral-500">No models match filters.</p>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                    {rows.map(m => <ModelCard key={m.id} record={m} isAdmin={isAdmin} onToggle={(rec) => handleToggle(p.id, rec)} isRunning={runningModels.has(m.model_id)} />)}
                  </div>
                )
              )}
            </section>
          )
        })
      )}

      {isAdmin && (
        <div className="bg-surface-raised border border-surface-border rounded-xl p-6">
          <h2 className="text-base font-semibold text-white mb-1">Pull New Model (local Ollama)</h2>
          <p className="text-xs text-yellow-400 bg-yellow-900/20 border border-yellow-800/30 rounded px-3 py-2 mb-4">
            ⚠️ Downloads can be 1–10 GB. After pulling, refresh above.
          </p>
          <div className="flex gap-3">
            <input type="text" value={pullName} onChange={e => setPullName(e.target.value)}
              placeholder="e.g. llama3.2:3b" disabled={pulling}
              className="flex-1 rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:opacity-50" />
            <button onClick={handlePull} disabled={pulling || !pullName.trim()}
              className="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-medium hover:bg-cyan-500 disabled:opacity-50">
              {pulling ? 'Pulling…' : 'Pull'}
            </button>
          </div>
          {pullLog.length > 0 && (
            <div ref={pullLogRef} className="mt-3 font-mono text-xs bg-surface text-cyan-400 rounded-lg p-3 max-h-40 overflow-y-auto border border-surface-border">
              {pullLog.map((line, i) => <div key={i}>{line}</div>)}
            </div>
          )}
        </div>
      )}

      {editingProvider && (
        <ProviderSettingsModal
          provider={editingProvider}
          onClose={() => setEditingProvider(null)}
          onSave={handleUpdateProvider}
        />
      )}
    </div>
  )
}
