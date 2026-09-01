import { useEffect, useState } from 'react'
import {
  providersApi, ProviderResponse, ProviderCreate, ProviderUpdate,
  ProviderTestResult, ProviderPreset,
  PROVIDER_LABELS, ENV_LABELS,
} from '../api/providers'
import { useAuthStore } from '../stores/authStore'
import { useUIStore } from '../stores/uiStore'

const ENV_DEFAULT: Record<ProviderType, 'local' | 'cloud' | 'custom'> = {
  ollama: 'local', openai: 'cloud', anthropic: 'cloud', gemini: 'cloud',
  openai_compatible: 'custom', openrouter: 'cloud', opencode_zen: 'cloud', nvidia: 'cloud',
}
type ProviderType = ProviderResponse['provider_type']

function TypeBadge({ type }: { type: ProviderType }) {
  const colors: Record<ProviderType, string> = {
    ollama: 'bg-cyan-500/10 text-cyan-400', openai: 'bg-blue-900/30 text-blue-400',
    anthropic: 'bg-orange-900/30 text-orange-400', gemini: 'bg-purple-900/30 text-purple-400',
    openai_compatible: 'bg-neutral-800 text-neutral-400', openrouter: 'bg-indigo-900/30 text-indigo-400',
    opencode_zen: 'bg-cyan-900/30 text-cyan-400', nvidia: 'bg-lime-900/30 text-lime-400',
  }
  return <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${colors[type]}`}>{PROVIDER_LABELS[type] ?? type}</span>
}

function PresetPicker({ presets, onPick, onCustom, onClose }: {
  presets: ProviderPreset[]; onPick: (p: ProviderPreset) => void; onCustom: () => void; onClose: () => void
}) {
  const icons: Record<string, string> = { openrouter: '🌐', opencode_zen: '🧩', nvidia: '🎮', ollama: '🦙', ollama_docker: '🐳', openai_compatible: '⚙️' }
  return (
    <div className="fixed inset-0 bg-black/60 z-40 flex items-center justify-center p-4">
      <div className="bg-surface-raised border border-surface-border rounded-xl shadow-xl w-full max-w-xl" role="dialog" aria-modal="true">
        <div className="flex items-center justify-between p-6 border-b border-surface-border">
          <h2 className="text-lg font-semibold text-white">Choose a Provider</h2>
          <button onClick={onClose} aria-label="Close" className="text-neutral-500 hover:text-neutral-300">✕</button>
        </div>
        <div className="p-6 grid grid-cols-1 sm:grid-cols-2 gap-3 max-h-[70vh] overflow-y-auto">
          {presets.map((p) => (
            <button key={p.id} onClick={() => onPick(p)}
              className="text-left p-4 rounded-lg border border-surface-border hover:border-cyan-500/50 hover:bg-surface-muted transition-colors">
              <div className="flex items-center gap-2 mb-1">
                <span>{icons[p.id] ?? '🔌'}</span>
                <span className="font-semibold text-sm text-neutral-100">{p.label}</span>
                {p.requires_api_key ? (
                  <span className="ml-auto text-[10px] uppercase tracking-wide bg-blue-900/30 text-blue-400 px-1.5 py-0.5 rounded">API key</span>
                ) : (
                  <span className="ml-auto text-[10px] uppercase tracking-wide bg-cyan-500/10 text-cyan-400 px-1.5 py-0.5 rounded">No key</span>
                )}
              </div>
              <p className="text-xs text-neutral-500 leading-snug">{p.description}</p>
            </button>
          ))}
        </div>
        <div className="px-6 pb-5 pt-1 flex justify-between items-center">
          <p className="text-xs text-neutral-500">Models are discovered automatically after saving.</p>
          <button onClick={onCustom} className="text-sm text-cyan-400 hover:text-cyan-300 font-medium">Advanced →</button>
        </div>
      </div>
    </div>
  )
}

function ProviderForm({ initial, preset, onSave, onClose }: {
  initial?: ProviderResponse; preset?: ProviderPreset | null
  onSave: (data: ProviderCreate | ProviderUpdate) => Promise<void>; onClose: () => void
}) {
  const isEdit = !!initial
  const [ptype, setPtype] = useState<ProviderType>(initial?.provider_type ?? preset?.provider_type ?? 'openai_compatible')
  const [name, setName] = useState(initial?.name ?? (preset ? `My ${preset.label}` : ''))
  const [baseUrl, setBaseUrl] = useState(initial?.base_url ?? preset?.default_base_url ?? '')
  const [apiKey, setApiKey] = useState('')
  const [replaceKey, setReplaceKey] = useState(false)
  const [description, setDescription] = useState(initial?.description ?? '')
  const [supportsEmbed, setSupportsEmbed] = useState(initial?.supports_embeddings ?? false)
  const [enabled, setEnabled] = useState(initial?.enabled ?? true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [testingConn, setTestingConn] = useState(false)
  const [connResult, setConnResult] = useState<{ ok: boolean; message: string } | null>(null)

  const requiresApiKey = preset?.requires_api_key ?? ['openai', 'anthropic', 'gemini'].includes(ptype)
  const baseUrlRequired = preset ? preset.id === 'openai_compatible' : true
  const apiKeyHint = preset?.api_key_hint ?? 'sk-…'
  const baseUrlRequiredFinal = isEdit ? false : baseUrlRequired

  const testConnection = async () => {
    setError(''); setConnResult(null)
    if (!baseUrl.trim()) { setConnResult({ ok: false, message: 'Base URL is required' }); return }
    setTestingConn(true)
    try {
      const payload: ProviderCreate = {
        name: `__conn_test_${Date.now()}`, provider_type: ptype, environment: ENV_DEFAULT[ptype],
        base_url: baseUrl || undefined, supports_streaming: true, supports_embeddings: supportsEmbed,
      }
      if (apiKey) payload.api_key = apiKey
      const created = await providersApi.create(payload)
      let result: ProviderTestResult
      try { result = await providersApi.test(created.id) } finally { await providersApi.delete(created.id).catch(() => undefined) }
      if (result.success && result.models_found != null) setConnResult({ ok: true, message: `✓ ${result.models_found} models available (${result.latency_ms}ms)` })
      else if (result.success) setConnResult({ ok: true, message: `✓ Connected (${result.latency_ms}ms)` })
      else setConnResult({ ok: false, message: result.error || 'Connection failed' })
    } catch (err: any) {
      setConnResult({ ok: false, message: err?.response?.status === 403 ? 'Admin role required' : err?.response?.data?.error?.message || 'Connection failed' })
    } finally { setTestingConn(false) }
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setError(''); setLoading(true)
    try {
      const payload: Record<string, unknown> = { name, environment: ENV_DEFAULT[ptype], supports_streaming: true, supports_embeddings: supportsEmbed, description: description || undefined, enabled }
      if (!isEdit) payload.provider_type = ptype
      if (baseUrl) payload.base_url = baseUrl
      if ((requiresApiKey || replaceKey) && apiKey) payload.api_key = apiKey
      await onSave(payload as ProviderCreate | ProviderUpdate); onClose()
    } catch (err: any) { setError(err?.response?.data?.error?.message || 'Failed to save') }
    finally { setLoading(false) }
  }

  const inputCls = "w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:ring-2 focus:ring-cyan-500"
  const labelCls = "block text-sm font-medium text-neutral-300 mb-1"

  return (
    <div className="fixed inset-0 bg-black/60 z-40 flex items-center justify-center p-4">
      <div className="bg-surface-raised border border-surface-border rounded-xl shadow-xl w-full max-w-lg" role="dialog" aria-modal="true">
        <div className="flex items-center justify-between p-6 border-b border-surface-border">
          <h2 className="text-lg font-semibold text-white">{isEdit ? 'Edit Provider' : 'Add LLM Provider'}</h2>
          <button onClick={onClose} className="text-neutral-500 hover:text-neutral-300">✕</button>
        </div>
        <form onSubmit={submit}>
          <div className="p-6 space-y-4 max-h-[70vh] overflow-y-auto">
            {error && <div className="p-3 bg-red-900/20 border border-red-800/40 rounded-lg text-sm text-red-400" role="alert">{error}</div>}
            {!isEdit && (
              <div>
                <label className={labelCls}>Provider <span className="text-red-400">*</span></label>
                {preset ? (
                  <div className="flex items-center gap-2 rounded-lg border border-surface-border bg-surface px-3 py-2">
                    <span className="text-sm font-medium text-neutral-200">{preset.label}</span>
                    <span className="text-xs text-neutral-500">{ENV_LABELS[preset.environment]}</span>
                    <button type="button" onClick={() => window.location.reload()} className="ml-auto text-xs text-cyan-400 hover:text-cyan-300">Change</button>
                  </div>
                ) : <input type="text" value={PROVIDER_LABELS[ptype] ?? ptype} disabled className={inputCls + ' opacity-60'} />}
              </div>
            )}
            <div>
              <label className={labelCls}>Display Name <span className="text-red-400">*</span></label>
              <input type="text" value={name} onChange={e => setName(e.target.value)} required placeholder={`e.g. My ${PROVIDER_LABELS[ptype]}`} className={inputCls} />
            </div>
            <div className="rounded-lg border border-surface-border p-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs text-neutral-500">Models are discovered automatically after saving.</p>
                {!isEdit && (
                  <button type="button" onClick={testConnection} disabled={testingConn}
                    className="flex-shrink-0 px-3 py-1.5 text-xs font-medium border border-cyan-600/50 text-cyan-400 rounded-lg hover:bg-surface-muted disabled:opacity-50">
                    {testingConn ? 'Testing…' : '⚡ Test Connection'}
                  </button>
                )}
              </div>
              {connResult && <p className={`mt-2 text-xs font-medium ${connResult.ok ? 'text-cyan-400' : 'text-red-400'}`}>{connResult.message}</p>}
            </div>
            <div>
              <label className={labelCls}>Base URL {baseUrlRequiredFinal && !preset && <span className="text-red-400 ml-1">*</span>}</label>
              <input type="url" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} required={baseUrlRequiredFinal} placeholder={preset?.default_base_url || 'https://...'} className={inputCls + ' font-mono'} />
            </div>
            {(requiresApiKey || preset?.id === 'openai_compatible') ? (
              <div>
                <label className={labelCls}>API Key</label>
                {isEdit && initial?.has_api_key ? (
                  <>
                    <div className="flex items-center gap-2">
                      <span className="flex-1 rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-neutral-500 font-mono">{initial.api_key_masked ?? '••••••••'}</span>
                      <button type="button" onClick={() => setReplaceKey(r => !r)} className="text-xs text-cyan-400 hover:text-cyan-300 px-2">{replaceKey ? 'Cancel' : 'Replace'}</button>
                    </div>
                    {replaceKey && <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="New API key" autoComplete="new-password" className={inputCls + ' mt-2'} />}
                  </>
                ) : (
                  <>
                    <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} required={requiresApiKey && !isEdit} placeholder={apiKeyHint} autoComplete="new-password" className={inputCls} />
                    <p className="text-xs text-neutral-500 mt-1">🔒 Stored securely; never returned in full.</p>
                  </>
                )}
              </div>
            ) : (
              <p className="text-xs text-cyan-400 bg-cyan-500/10 border border-surface-border rounded-lg px-3 py-2">✓ No API key required</p>
            )}
            <div>
              <label className={labelCls}>Description (optional)</label>
              <input type="text" value={description} onChange={e => setDescription(e.target.value)} placeholder="e.g. Company internal AI gateway" className={inputCls} />
            </div>
            <div className="flex items-center gap-4 pt-1">
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
            <button type="submit" disabled={loading || !name.trim()} className="px-4 py-2 text-sm font-medium text-white bg-cyan-600 rounded-lg hover:bg-cyan-500 disabled:opacity-50">{loading ? 'Saving…' : isEdit ? 'Save Changes' : 'Save Provider'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

function ProviderCard({ provider, isAdmin, onEdit, onDelete, onTest }: {
  provider: ProviderResponse; isAdmin: boolean; onEdit: () => void; onDelete: () => void; onTest: () => void
}) {
  return (
    <div className={`bg-surface-raised border rounded-xl p-5 transition-all ${provider.enabled ? 'border-surface-border' : 'border-surface-border opacity-60'}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <h3 className="font-semibold text-neutral-100 text-sm">{provider.name}</h3>
            <TypeBadge type={provider.provider_type} />
            <span className="text-xs text-neutral-500">{ENV_LABELS[provider.environment]}</span>
            {!provider.enabled && <span className="text-xs bg-neutral-800 text-neutral-500 px-2 py-0.5 rounded-full">disabled</span>}
          </div>
          {provider.base_url && <p className="font-mono text-xs text-neutral-500 truncate">{provider.base_url}</p>}
          {provider.model_name && <p className="text-xs text-neutral-500 truncate mt-0.5">pinned: <span className="font-mono">{provider.model_name}</span></p>}
          {provider.description && <p className="text-xs text-neutral-500 mt-1">{provider.description}</p>}
          <div className="flex gap-3 mt-2 text-xs text-neutral-500 flex-wrap items-center">
            <span className={`px-2 py-0.5 rounded-full font-medium ${
              provider.enabled ? 'bg-cyan-500/10 text-cyan-400 border border-surface-border' : 'bg-neutral-800 text-neutral-500 border border-neutral-700'
            }`}>{provider.enabled ? '✓ connected' : 'disabled'}</span>
            <span>{provider.model_count} model{provider.model_count === 1 ? '' : 's'}</span>
            {provider.has_api_key && <span title="API key stored">🔑 {provider.api_key_masked ?? '••••••••'}</span>}
          </div>
        </div>
        {isAdmin && (
          <div className="flex gap-1 flex-shrink-0">
            <button onClick={onTest} className="text-xs px-2 py-1 text-neutral-400 hover:text-cyan-400 border border-surface-border rounded-lg transition-colors" title="Test connection">Test</button>
            <button onClick={onEdit} className="text-xs px-2 py-1 text-neutral-400 hover:text-cyan-400 border border-surface-border rounded-lg transition-colors">Edit</button>
            <button onClick={onDelete} className="text-xs px-2 py-1 text-neutral-400 hover:text-red-400 border border-surface-border rounded-lg transition-colors">✕</button>
          </div>
        )}
      </div>
    </div>
  )
}

export default function ProvidersPage() {
  const { user } = useAuthStore()
  const { addToast } = useUIStore()
  const isAdmin = user?.role === 'admin'
  const [providers, setProviders] = useState<ProviderResponse[]>([])
  const [presets, setPresets] = useState<ProviderPreset[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState<null | 'pick' | { form: true; preset: ProviderPreset | null }>(null)
  const [editTarget, setEditTarget] = useState<ProviderResponse | null>(null)
  const [testResult, setTestResult] = useState<{ id: string; result: ProviderTestResult } | null>(null)
  const [testing, setTesting] = useState<string | null>(null)

  const load = async () => {
    const [ps, pr] = await Promise.allSettled([providersApi.list(), providersApi.presets()])
    if (ps.status === 'fulfilled') setProviders(ps.value)
    if (pr.status === 'fulfilled') setPresets(pr.value)
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  const handleCreate = async (data: any) => {
    const p = await providersApi.create(data)
    setProviders(prev => [...prev, p])
    addToast({ type: 'success', title: 'Provider added', message: p.name })
    try {
      await providersApi.refreshModels(p.id)
      await load()
    } catch { addToast({ type: 'warning' as any, title: 'Saved — discovery failed' } as any) }
  }
  const handleUpdate = async (id: string, data: any) => {
    const p = await providersApi.update(id, data)
    setProviders(prev => prev.map(x => x.id === id ? p : x))
    addToast({ type: 'success', title: 'Provider updated' })
  }
  const handleDelete = async (id: string, name: string) => {
    if (!window.confirm(`Delete "${name}"?`)) return
    await providersApi.delete(id)
    setProviders(prev => prev.filter(p => p.id !== id))
    addToast({ type: 'info', title: 'Provider deleted' })
  }
  const handleTest = async (id: string) => {
    setTesting(id); setTestResult(null)
    try {
      const result = await providersApi.test(id)
      setTestResult({ id, result })
      addToast({ type: result.success ? 'success' : 'error', title: result.success ? 'Connection OK' : 'Failed', message: result.success ? `${result.models_found ?? '?'} models · ${result.latency_ms}ms` : result.error || 'Connection failed' })
    } catch { addToast({ type: 'error', title: 'Test failed' }) }
    finally { setTesting(null) }
  }

  const local = providers.filter(p => p.environment === 'local')
  const cloud = providers.filter(p => p.environment === 'cloud')
  const custom = providers.filter(p => p.environment === 'custom')

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">LLM Providers</h1>
          <p className="text-sm text-neutral-400 mt-1">Configure AI model providers — local, cloud, or custom endpoints</p>
        </div>
        {isAdmin && (
          <button onClick={() => setShowCreate('pick')}
            className="flex items-center gap-2 px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-medium hover:bg-cyan-500 transition-colors">
            + Add Provider
          </button>
        )}
      </div>

      <div className="p-4 bg-surface-overlay border border-surface-border rounded-xl text-sm text-cyan-400">
        <strong>Model-agnostic:</strong> Use a fully local model for data sovereignty, a cloud model when permitted, or connect your own AI infrastructure.
      </div>

      {testResult && (
        <div className={`p-3 rounded-lg border text-sm flex items-center justify-between ${
          testResult.result.success ? 'bg-cyan-500/10 border-surface-border text-cyan-400' : 'bg-red-900/20 border-red-800/40 text-red-400'}`}>
          <span>{testResult.result.success ? `✓ Connected — ${testResult.result.models_found ?? '?'} models (${testResult.result.latency_ms}ms)` : `✗ ${testResult.result.error}`}</span>
          <button onClick={() => setTestResult(null)} className="opacity-60 hover:opacity-100 ml-2">✕</button>
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[...Array(2)].map((_, i) => <div key={i} className="bg-surface-raised border border-surface-border rounded-xl h-28 animate-pulse" />)}
        </div>
      ) : providers.length === 0 ? (
        <div className="flex flex-col items-center justify-center min-h-48 text-center">
          <div className="text-4xl mb-3">🤖</div>
          <p className="text-neutral-400 font-medium">No providers configured yet</p>
          <p className="text-xs text-neutral-500 mt-1">Add an LLM provider to start using AI features</p>
          {isAdmin && (
            <button onClick={() => setShowCreate('pick')} className="mt-3 px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-medium hover:bg-cyan-500">
              + Add Your First Provider
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-6">
          {local.length > 0 && <div><h2 className="text-sm font-semibold text-cyan-700 uppercase tracking-wider mb-3">🖥 Local</h2><div className="grid grid-cols-1 md:grid-cols-2 gap-3">{local.map(p => <ProviderCard key={p.id} provider={p} isAdmin={isAdmin} onEdit={() => setEditTarget(p)} onDelete={() => handleDelete(p.id, p.name)} onTest={() => handleTest(p.id)} />)}</div></div>}
          {cloud.length > 0 && <div><h2 className="text-sm font-semibold text-cyan-700 uppercase tracking-wider mb-3">☁️ Cloud</h2><div className="grid grid-cols-1 md:grid-cols-2 gap-3">{cloud.map(p => <ProviderCard key={p.id} provider={p} isAdmin={isAdmin} onEdit={() => setEditTarget(p)} onDelete={() => handleDelete(p.id, p.name)} onTest={() => handleTest(p.id)} />)}</div></div>}
          {custom.length > 0 && <div><h2 className="text-sm font-semibold text-cyan-700 uppercase tracking-wider mb-3">⚙️ Custom</h2><div className="grid grid-cols-1 md:grid-cols-2 gap-3">{custom.map(p => <ProviderCard key={p.id} provider={p} isAdmin={isAdmin} onEdit={() => setEditTarget(p)} onDelete={() => handleDelete(p.id, p.name)} onTest={() => handleTest(p.id)} />)}</div></div>}
        </div>
      )}

      {showCreate === 'pick' && <PresetPicker presets={presets} onPick={(preset) => setShowCreate({ form: true, preset })} onCustom={() => setShowCreate({ form: true, preset: null })} onClose={() => setShowCreate(null)} />}
      {showCreate && showCreate !== 'pick' && <ProviderForm preset={showCreate.preset} onClose={() => setShowCreate(null)} onSave={handleCreate} />}
      {editTarget && <ProviderForm initial={editTarget} onClose={() => setEditTarget(null)} onSave={(data) => handleUpdate(editTarget.id, data)} />}
    </div>
  )
}
