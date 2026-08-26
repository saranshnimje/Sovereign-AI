/**
 * Models page — all discovered models grouped by provider.
 *
 * Data flow:  Provider → adapter → live discovery → persisted catalog → this page
 * No model lists are hard-coded anywhere in the frontend.
 *
 * Per-provider actions: Refresh Models · Test Connection · Configure (→ Providers page)
 * Per-model actions:    Enable/Disable (admin) · Test · Use in Chat
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  providersApi, prefsApi,
  ModelRecord, ProviderResponse, ProviderTestResult,
} from '../api/providers'
import { systemApi } from '../api/system'
import { useAuthStore } from '../stores/authStore'
import { useUIStore } from '../stores/uiStore'

function formatSize(bytes?: number | null): string {
  if (!bytes) return ''
  if (bytes > 1e9) return `${(bytes / 1e9).toFixed(1)} GB`
  return `${(bytes / 1e6).toFixed(0)} MB`
}

/* ------------------------------------------------------------------ */
/* Model card                                                          */
/* ------------------------------------------------------------------ */
function ModelCard({ record, isAdmin, onToggle }: {
  record: ModelRecord
  isAdmin: boolean
  onToggle: (r: ModelRecord) => void
}) {
  const navigate = useNavigate()
  const { addToast } = useUIStore()
  const [testing, setTesting] = useState(false)

  // Only metadata the provider actually returned — never placeholders
  const meta = [
    record.family,
    record.parameter_size,
    formatSize(record.size_bytes),
    record.quantization,
    record.context_length ? `${record.context_length.toLocaleString()} ctx` : null,
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
    } catch {
      addToast({ type: 'error', title: 'Test failed' })
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className={`bg-white dark:bg-neutral-800 rounded-lg shadow-sm border p-4 transition-all
      ${unavailable ? 'opacity-50 border-neutral-100 dark:border-neutral-800'
        : record.enabled ? 'border-neutral-200 dark:border-neutral-700'
        : 'border-dashed border-neutral-300 dark:border-neutral-600'}`}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="min-w-0">
          <h3 className="font-mono text-sm font-semibold text-neutral-800 dark:text-neutral-100 truncate"
              title={record.model_id}>
            {record.model_id}
          </h3>
          {meta.length > 0 && (
            <p className="text-xs text-neutral-400 mt-0.5">{meta.join(' · ')}</p>
          )}
        </div>
        <div className="flex flex-col gap-1 items-end flex-shrink-0">
          <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
            unavailable ? 'bg-neutral-100 text-neutral-500'
            : 'bg-success-100 text-success-700'}`}>
            {unavailable ? 'unavailable' : 'available'}
          </span>
          {!record.enabled && !unavailable && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-warning-50 text-warning-700">disabled</span>
          )}
        </div>
      </div>

      {isAdmin && (
        <div className="flex gap-1.5 flex-wrap mt-2">
          <button
            onClick={() => onToggle(record)}
            disabled={unavailable}
            className={`text-xs px-2 py-1 rounded border transition-colors disabled:opacity-40 ${
              record.enabled
                ? 'bg-primary-600 text-white border-primary-600 hover:bg-primary-700'
                : 'border-neutral-300 text-neutral-600 hover:bg-primary-50 hover:border-primary-300 dark:border-neutral-600 dark:text-neutral-300'
            }`}>
            {record.enabled ? '✓ Enabled' : 'Enable'}
          </button>
          {record.enabled && (
            <>
              <button onClick={handleTest} disabled={testing}
                className="text-xs px-2 py-1 rounded border border-neutral-300 text-neutral-600 hover:bg-neutral-50 disabled:opacity-40 dark:border-neutral-600 dark:text-neutral-300">
                {testing ? '…' : 'Test'}
              </button>
              <button onClick={() => navigate(`/chat?model=${encodeURIComponent(record.model_id)}&provider=${record.provider_id}`)}
                disabled={unavailable}
                className="text-xs px-2 py-1 rounded border border-indigo-300 text-indigo-700 hover:bg-indigo-50 disabled:opacity-40 dark:border-indigo-700 dark:text-indigo-300">
                💬 Use in Chat
              </button>
            </>
          )}
          {!record.enabled && (
            <button onClick={() => onToggle(record)}
              className="text-xs px-2 py-1 rounded border border-neutral-300 text-neutral-500 hover:bg-neutral-50 dark:border-neutral-600">
              Enable to chat
            </button>
          )}
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */
export default function ModelsPage() {
  const { user } = useAuthStore()
  const { addToast } = useUIStore()
  const isAdmin = user?.role === 'admin'
  const navigate = useNavigate()

  const [providers, setProviders] = useState<ProviderResponse[]>([])
  const [catalog, setCatalog] = useState<Record<string, ModelRecord[]>>({})   // provider_id → models
  const [loading, setLoading] = useState(true)
  const [refreshingId, setRefreshingId] = useState<string | null>(null)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{ name: string; result: ProviderTestResult } | null>(null)

  // Filters
  const [search, setSearch] = useState('')
  const [providerFilter, setProviderFilter] = useState<string>('all')
  const [statusFilter, setStatusFilter] = useState<'all' | 'enabled' | 'disabled'>('all')
  const [sortAsc, setSortAsc] = useState(true)

  // Pull state (admin; targets the default local Ollama instance)
  const [pullName, setPullName] = useState('')
  const [pulling, setPulling] = useState(false)
  const [pullLog, setPullLog] = useState<string[]>([])
  const pullLogRef = useRef<HTMLDivElement>(null)

  /** Load providers + their persisted catalogs in parallel. */
  const loadAll = useCallback(async () => {
    try {
      const ps = await providersApi.list()
      setProviders(ps)
      const results = await Promise.allSettled(ps.map(p => providersApi.getModels(p.id)))
      const next: Record<string, ModelRecord[]> = {}
      ps.forEach((p, i) => { next[p.id] = results[i].status === 'fulfilled' ? results[i].value : [] })
      setCatalog(next)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  useEffect(() => {
    if (pullLogRef.current) pullLogRef.current.scrollTop = pullLogRef.current.scrollHeight
  }, [pullLog])

  /** Live refresh for one provider. */
  const handleRefresh = async (p: ProviderResponse) => {
    setRefreshingId(p.id)
    try {
      const rows = await providersApi.refreshModels(p.id)
      setCatalog(prev => ({ ...prev, [p.id]: rows }))
      const avail = rows.filter(m => m.status === 'available').length
      addToast({ type: 'success', title: `Refreshed ${p.name}`, message: `${avail} models available` })
    } catch (err: any) {
      addToast({
        type: 'error', title: `Could not refresh ${p.name}`,
        message: err?.response?.data?.detail || 'Provider unreachable',
      })
    } finally {
      setRefreshingId(null)
    }
  }

  const handleRefreshAll = async () => {
    for (const p of providers.filter(x => x.enabled)) {
      await handleRefresh(p)
    }
  }

  const handleTestProvider = async (p: ProviderResponse) => {
    if (!isAdmin) return
    setTestingId(p.id)
    try {
      const result = await providersApi.test(p.id)
      setTestResult({ name: p.name, result })
    } catch {
      addToast({ type: 'error', title: 'Test failed', message: 'Admin role required or network error' })
    } finally {
      setTestingId(null)
    }
  }

  const handleToggle = async (providerId: string, r: ModelRecord) => {
    try {
      const updated = await providersApi.setModelEnabled(providerId, r.id, !r.enabled)
      setCatalog(prev => ({
        ...prev,
        [providerId]: (prev[providerId] || []).map(m => m.id === updated.id ? updated : m),
      }))
      addToast({ type: 'success', title: `${updated.model_id} ${updated.enabled ? 'enabled' : 'disabled'}` })
    } catch {
      addToast({ type: 'error', title: 'Failed to update model' })
    }
  }

  const handleUseInChat = async (p: ProviderResponse, r: ModelRecord) => {
    try {
      await prefsApi.set(p.id, r.model_id)
      addToast({ type: 'success', title: 'Default model set', message: `${p.name} / ${r.model_id}` })
    } catch { /* non-fatal */ }
    navigate(`/chat?model=${encodeURIComponent(r.model_id)}&provider=${p.id}`)
  }

  const handlePull = async () => {
    const name = pullName.trim()
    if (!name) return
    setPulling(true)
    setPullLog([`Starting pull: ${name}`])
    try {
      const resp = await fetch('/api/v1/models/pull', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${useAuthStore.getState().accessToken}`,
        },
        body: JSON.stringify({ model_name: name }),
      })
      if (!resp.ok || !resp.body) {
        setPullLog(prev => [...prev, `Error: HTTP ${resp.status}`])
        return
      }
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
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
              const msg = data.status || data.message
              if (msg) setPullLog(prev => [...prev.slice(-50), msg])
            } catch { /* ignore */ }
          }
        }
      }
      setPullLog(prev => [...prev, `✓ Pulled ${name} — refresh the Ollama provider to see it`])
      setPullName('')
    } catch (err: any) {
      setPullLog(prev => [...prev, `Error: ${err.message}`])
    } finally {
      setPulling(false)
    }
  }

  /* ---------------- filtering / sorting ---------------- */
  const filteredProviders = useMemo(() =>
    providerFilter === 'all' ? providers : providers.filter(p => p.id === providerFilter),
    [providers, providerFilter])

  const matchesFilters = (m: ModelRecord) => {
    if (search && !m.model_id.toLowerCase().includes(search.toLowerCase())) return false
    if (statusFilter === 'enabled' && !(m.enabled && m.status === 'available')) return false
    if (statusFilter === 'disabled' && (m.enabled && m.status === 'available')) return false
    return true
  }

  const totalAvailable = Object.values(catalog).flat()
    .filter(m => m.enabled && m.status === 'available').length

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">Models</h1>
          <p className="text-sm text-neutral-500 mt-1">
            Discovered from your providers — grouped by connection
          </p>
        </div>
        <button onClick={handleRefreshAll}
          disabled={refreshingId !== null || providers.length === 0}
          className="px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700 disabled:opacity-50 transition-colors">
          {refreshingId ? '⟳ Refreshing…' : '↻ Refresh All'}
        </button>
      </div>

      {/* Test result banner */}
      {testResult && (
        <div className={`p-3 rounded-lg border text-sm flex items-center justify-between ${
          testResult.result.success
            ? 'bg-success-50 border-success-200 text-success-800'
            : 'bg-danger-50 border-danger-200 text-danger-700'}`}>
          <span>
            {testResult.result.success
              ? `✓ ${testResult.name} connected — ${testResult.result.models_found ?? '?'} models available (${testResult.result.latency_ms}ms)`
              : `✗ ${testResult.name}: ${testResult.result.error || 'Connection failed'}`}
          </span>
          <button onClick={() => setTestResult(null)} className="opacity-60 hover:opacity-100 ml-2">✕</button>
        </div>
      )}

      {/* Search + filters */}
      <div className="flex gap-3 flex-wrap items-center">
        <input type="search" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search models…"
          aria-label="Search models"
          className="flex-1 min-w-48 rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 placeholder-neutral-400 focus:outline-none focus:ring-2 focus:ring-primary-500" />
        <select value={providerFilter} onChange={e => setProviderFilter(e.target.value)}
          aria-label="Filter by provider"
          className="rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm text-neutral-800 dark:text-neutral-100">
          <option value="all">All Providers</option>
          {providers.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value as any)}
          aria-label="Filter by status"
          className="rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm text-neutral-800 dark:text-neutral-100">
          <option value="all">All Status</option>
          <option value="enabled">Enabled</option>
          <option value="disabled">Disabled / Unavailable</option>
        </select>
        <button onClick={() => setSortAsc(a => !a)}
          className="text-sm text-primary-600 hover:underline whitespace-nowrap">
          Sort {sortAsc ? 'A→Z' : 'Z→A'}
        </button>
      </div>

      {/* Content */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => <div key={i} className="bg-neutral-100 dark:bg-neutral-800 rounded-lg h-32 animate-pulse" />)}
        </div>
      ) : providers.length === 0 ? (
        <div className="flex flex-col items-center justify-center min-h-48 text-center">
          <div className="text-4xl mb-3" aria-hidden="true">🔌</div>
          <p className="text-neutral-600 dark:text-neutral-400 font-medium">No providers configured</p>
          {isAdmin && (
            <button onClick={() => navigate('/providers')}
              className="mt-3 px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700">
              + Add a Provider first
            </button>
          )}
        </div>
      ) : (
        filteredProviders.map(p => {
          const rows = (catalog[p.id] ?? [])
            .filter(matchesFilters)
            .sort((a, b) => sortAsc
              ? a.model_id.localeCompare(b.model_id)
              : b.model_id.localeCompare(a.model_id))
          const availableCount = (catalog[p.id] ?? []).filter(m => m.enabled && m.status === 'available').length

          return (
            <section key={p.id}>
              {/* Provider group header */}
              <div className="flex items-center justify-between flex-wrap gap-2 mb-3 pb-2 border-b border-neutral-200 dark:border-neutral-700">
                <div className="flex items-center gap-2 flex-wrap">
                  <h2 className="text-base font-bold text-neutral-800 dark:text-neutral-100">{p.name}</h2>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    p.enabled ? 'bg-success-50 text-success-700' : 'bg-neutral-100 text-neutral-500'}`}>
                    {p.enabled ? `✓ ${availableCount} available` : 'disabled'}
                  </span>
                  <span className="text-xs text-neutral-400 font-mono">{p.base_url}</span>
                </div>
                <div className="flex gap-1.5">
                  <button onClick={() => handleRefresh(p)} disabled={refreshingId === p.id}
                    className="text-xs px-2.5 py-1.5 border border-neutral-300 dark:border-neutral-600 text-neutral-600 dark:text-neutral-300 rounded-md hover:bg-neutral-50 dark:hover:bg-neutral-700 disabled:opacity-50">
                    {refreshingId === p.id ? '⟳ Discovering…' : '↻ Refresh Models'}
                  </button>
                  {isAdmin && (
                    <>
                      <button onClick={() => handleTestProvider(p)} disabled={testingId === p.id}
                        className="text-xs px-2.5 py-1.5 border border-neutral-300 dark:border-neutral-600 text-neutral-600 dark:text-neutral-300 rounded-md hover:bg-neutral-50 dark:hover:bg-neutral-700 disabled:opacity-50">
                        {testingId === p.id ? 'Testing…' : '⚡ Test Connection'}
                      </button>
                      <button onClick={() => navigate('/providers')}
                        className="text-xs px-2.5 py-1.5 border border-neutral-300 dark:border-neutral-600 text-neutral-600 dark:text-neutral-300 rounded-md hover:bg-neutral-50 dark:hover:bg-neutral-700">
                        ⚙ Configure
                      </button>
                    </>
                  )}
                </div>
              </div>

              {rows.length === 0 ? (
                (catalog[p.id] ?? []).length === 0 ? (
                  <div className="text-center py-8 bg-neutral-50 dark:bg-neutral-800/50 rounded-lg border border-dashed border-neutral-200 dark:border-neutral-700">
                    <p className="text-sm text-neutral-500">No models discovered yet for this provider.</p>
                    <button onClick={() => handleRefresh(p)} disabled={refreshingId === p.id}
                      className="mt-2 text-sm text-primary-600 hover:underline">
                      {refreshingId === p.id ? 'Discovering…' : 'Refresh Models now →'}
                    </button>
                  </div>
                ) : (
                  <p className="text-center py-6 text-sm text-neutral-400">No models match the current filters.</p>
                )
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                  {rows.map(m => (
                    <ModelCard key={m.id} record={m} isAdmin={isAdmin}
                      onToggle={(rec) => handleToggle(p.id, rec)} />
                  ))}
                </div>
              )}
            </section>
          )
        })
      )}

      {/* Pull new model (admin only — targets the default local Ollama instance) */}
      {isAdmin && (
        <div className="bg-white dark:bg-neutral-800 rounded-lg shadow-sm border border-neutral-200 dark:border-neutral-700 p-6">
          <h2 className="text-base font-semibold text-neutral-800 dark:text-neutral-100 mb-1">Pull New Model (local Ollama)</h2>
          <p className="text-xs text-warning-700 bg-warning-50 border border-warning-200 rounded px-3 py-2 mb-4">
            ⚠️ Downloads can be 1–10 GB. After pulling, refresh the Ollama provider above.
          </p>
          <div className="flex gap-3">
            <input type="text" value={pullName} onChange={e => setPullName(e.target.value)}
              placeholder="e.g. llama3.2:3b" disabled={pulling}
              className="flex-1 rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50" />
            <button onClick={handlePull} disabled={pulling || !pullName.trim()}
              className="px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700 disabled:opacity-50">
              {pulling ? 'Pulling…' : 'Pull'}
            </button>
          </div>
          {pullLog.length > 0 && (
            <div ref={pullLogRef}
              className="mt-3 font-mono text-xs bg-neutral-900 text-neutral-100 rounded p-3 max-h-40 overflow-y-auto">
              {pullLog.map((line, i) => <div key={i}>{line}</div>)}
            </div>
          )}
        </div>
      )}

      {/* keep totalAvailable referenced for header stats */}
      <span className="hidden">{totalAvailable}</span>
    </div>
  )
}
