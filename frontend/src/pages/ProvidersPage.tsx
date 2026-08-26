/**
 * LLM Providers page — manage AI provider CONNECTION configurations.
 *
 * A provider stores connection info only (name, type, base URL, API key).
 * Models are discovered automatically from the provider — see Models page.
 *
 * Security:
 * - API keys are WRITE-ONLY. This page never displays stored keys.
 * - Create/Update/Delete/Test require admin role (enforced server-side).
 * - API key inputs use type="password" fields.
 */
import { useEffect, useState } from 'react'
import {
  providersApi, ProviderResponse, ProviderCreate, ProviderUpdate,
  ProviderTestResult, ProviderPreset,
  PROVIDER_LABELS, ENV_LABELS,
} from '../api/providers'
import { useAuthStore } from '../stores/authStore'
import { useUIStore } from '../stores/uiStore'

// Provider type → environment default (used when creating without a preset)
const ENV_DEFAULT: Record<ProviderType, 'local' | 'cloud' | 'custom'> = {
  ollama: 'local',
  openai: 'cloud',
  anthropic: 'cloud',
  gemini: 'cloud',
  openai_compatible: 'custom',
  openrouter: 'cloud',
  opencode_zen: 'cloud',
  nvidia: 'cloud',
}

type ProviderType = ProviderResponse['provider_type']

function TypeBadge({ type }: { type: ProviderType }) {
  const colors: Record<ProviderType, string> = {
    ollama: 'bg-green-100 text-green-700',
    openai: 'bg-blue-100 text-blue-700',
    anthropic: 'bg-orange-100 text-orange-700',
    gemini: 'bg-purple-100 text-purple-700',
    openai_compatible: 'bg-neutral-100 text-neutral-600',
    openrouter: 'bg-indigo-100 text-indigo-700',
    opencode_zen: 'bg-cyan-100 text-cyan-700',
    nvidia: 'bg-lime-100 text-lime-700',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${colors[type]}`}>
      {PROVIDER_LABELS[type] ?? type}
    </span>
  )
}

// ------------------------------------------------------------------
// Provider preset picker — step 1 of "Add LLM Provider"
// Presets are fetched from the backend so new providers appear without
// frontend changes.
// ------------------------------------------------------------------
function PresetPicker({ presets, onPick, onCustom, onClose }: {
  presets: ProviderPreset[]
  onPick: (p: ProviderPreset) => void
  onCustom: () => void
  onClose: () => void
}) {
  const icons: Record<string, string> = {
    openrouter: '🌐', opencode_zen: '🧩', nvidia: '🎮',
    ollama: '🦙', openai_compatible: '⚙️',
  }
  return (
    <div className="fixed inset-0 bg-black/50 z-40 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-neutral-800 rounded-lg shadow-xl w-full max-w-xl"
           role="dialog" aria-modal="true" aria-labelledby="preset-title">
        <div className="flex items-center justify-between p-6 border-b border-neutral-200 dark:border-neutral-700">
          <h2 id="preset-title" className="text-lg font-semibold text-neutral-800 dark:text-neutral-100">
            Choose a Provider
          </h2>
          <button onClick={onClose} aria-label="Close" className="text-neutral-400 hover:text-neutral-600">✕</button>
        </div>
        <div className="p-6 grid grid-cols-1 sm:grid-cols-2 gap-3 max-h-[70vh] overflow-y-auto">
          {presets.map((p) => (
            <button key={p.id} onClick={() => onPick(p)}
              className={`text-left p-4 rounded-lg border border-neutral-200 dark:border-neutral-700 hover:border-primary-400 hover:bg-primary-50/40 dark:hover:bg-primary-900/10 transition-colors ${p.requires_api_key ? '' : ''}`}>
              <div className="flex items-center gap-2 mb-1">
                <span aria-hidden="true">{icons[p.id] ?? '🔌'}</span>
                <span className="font-semibold text-sm text-neutral-800 dark:text-neutral-100">{p.label}</span>
                {p.requires_api_key ? (
                  <span className="ml-auto text-[10px] uppercase tracking-wide bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded">API key</span>
                ) : (
                  <span className="ml-auto text-[10px] uppercase tracking-wide bg-green-50 text-green-600 px-1.5 py-0.5 rounded">No key</span>
                )}
              </div>
              <p className="text-xs text-neutral-500 dark:text-neutral-400 leading-snug">{p.description}</p>
            </button>
          ))}
        </div>
        <div className="px-6 pb-5 pt-1 flex justify-between items-center">
          <p className="text-xs text-neutral-400">Models are discovered automatically after saving.</p>
          <button onClick={onCustom}
            className="text-sm text-primary-600 hover:underline font-medium">
            Advanced (blank form) →
          </button>
        </div>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------
// Provider form (create / edit)
// ------------------------------------------------------------------
function ProviderForm({
  initial,
  preset,
  onSave,
  onClose,
}: {
  initial?: ProviderResponse
  preset?: ProviderPreset | null
  onSave: (data: ProviderCreate | ProviderUpdate) => Promise<void>
  onClose: () => void
}) {
  const isEdit = !!initial
  // Legacy types remain selectable via "Advanced"; presets drive normal flow
  const [ptype, setPtype] = useState<ProviderType>(
    initial?.provider_type ?? preset?.provider_type ?? 'openai_compatible')
  const [name, setName] = useState(
    initial?.name ?? (preset ? `My ${preset.label}` : ''))
  const [baseUrl, setBaseUrl] = useState(
    initial?.base_url ?? preset?.default_base_url ?? '')
  const [apiKey, setApiKey] = useState('')          // never pre-filled
  const [replaceKey, setReplaceKey] = useState(false)
  const [description, setDescription] = useState(initial?.description ?? '')
  const [supportsEmbed, setSupportsEmbed] = useState(initial?.supports_embeddings ?? false)
  const [enabled, setEnabled] = useState(initial?.enabled ?? true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  // Pre-save connection test state (create mode only — saved providers use card Test)
  const [testingConn, setTestingConn] = useState(false)
  const [connResult, setConnResult] = useState<
    { ok: boolean; message: string } | null
  >(null)

  // Field requirements come from the backend preset when available
  const requiresApiKey =
    preset?.requires_api_key ??
    ['openai', 'anthropic', 'gemini'].includes(ptype)
  const baseUrlRequired = preset ? preset.id === 'openai_compatible' : true
  const apiKeyHint = preset?.api_key_hint ?? 'sk-…'
  const baseUrlRequiredFinal = isEdit ? false : baseUrlRequired

  /** Test the connection using the CURRENT form values before saving. */
  const testConnection = async () => {
    setError('')
    setConnResult(null)
    if (!baseUrl.trim()) {
      setConnResult({ ok: false, message: 'Base URL is required to test the connection' })
      return
    }
    setTestingConn(true)
    try {
      // Create a throwaway provider scoped to this validation run, then delete it.
      // This reuses the server-side adapter stack without duplicating logic.
      const payload: ProviderCreate = {
        name: `__conn_test_${Date.now()}`,
        provider_type: ptype,
        environment: ENV_DEFAULT[ptype],
        base_url: baseUrl || undefined,
        supports_streaming: true,
        supports_embeddings: supportsEmbed,
      }
      if (apiKey) payload.api_key = apiKey

      const created = await providersApi.create(payload)
      let result: ProviderTestResult
      try {
        result = await providersApi.test(created.id)
      } finally {
        await providersApi.delete(created.id).catch(() => undefined)
      }

      if (result.success && result.models_found != null) {
        setConnResult({
          ok: true,
          message: `Connection successful · ${result.models_found} model${result.models_found === 1 ? '' : 's'} available (${result.latency_ms}ms)`,
        })
      } else if (result.success) {
        setConnResult({
          ok: true,
          message: `Connection successful (${result.latency_ms}ms) — model listing not supported by this endpoint`,
        })
      } else {
        setConnResult({ ok: false, message: result.error || 'Connection failed' })
      }
    } catch (err: any) {
      const msg =
        err?.response?.status === 403 ? 'Admin role required to test connections' :
        err?.response?.data?.error?.message || 'Connection failed'
      setConnResult({ ok: false, message: msg })
    } finally {
      setTestingConn(false)
    }
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const payload: Record<string, unknown> = {
        name,
        environment: ENV_DEFAULT[ptype],
        supports_streaming: true,
        supports_embeddings: supportsEmbed,
        description: description || undefined,
        enabled,
      }
      if (!isEdit) {
        payload.provider_type = ptype
      }
      if (baseUrl) payload.base_url = baseUrl
      if ((requiresApiKey || replaceKey) && apiKey) payload.api_key = apiKey
      await onSave(payload as ProviderCreate | ProviderUpdate)
      onClose()
    } catch (err: any) {
      setError(err?.response?.data?.error?.message || 'Failed to save')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-40 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-neutral-800 rounded-lg shadow-xl w-full max-w-lg"
           role="dialog" aria-modal="true" aria-labelledby="provider-form-title">
        <div className="flex items-center justify-between p-6 border-b border-neutral-200 dark:border-neutral-700">
          <h2 id="provider-form-title" className="text-lg font-semibold text-neutral-800 dark:text-neutral-100">
            {isEdit ? 'Edit Provider' : 'Add LLM Provider'}
          </h2>
          <button onClick={onClose} aria-label="Close" className="text-neutral-400 hover:text-neutral-600">✕</button>
        </div>

        <form onSubmit={submit}>
          <div className="p-6 space-y-4 max-h-[70vh] overflow-y-auto">
            {error && (
              <div className="p-3 bg-danger-50 border border-danger-200 rounded text-sm text-danger-700" role="alert">
                {error}
              </div>
            )}

            {/* Provider type — preset badge on create, fixed on edit */}
            {!isEdit && (
              <div>
                <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                  Provider <span className="text-danger-500">*</span>
                </label>
                {preset ? (
                  <div className="flex items-center gap-2 rounded-md border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-700/50 px-3 py-2">
                    <span className="text-sm font-medium text-neutral-800 dark:text-neutral-100">{preset.label}</span>
                    <span className="text-xs text-neutral-400">{ENV_LABELS[preset.environment]}</span>
                    <button type="button" onClick={() => window.location.reload()}
                      className="ml-auto text-xs text-primary-600 hover:underline">
                      Change
                    </button>
                  </div>
                ) : (
                  <input type="text" value={PROVIDER_LABELS[ptype] ?? ptype} disabled
                    className="w-full rounded-md border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-700/50 px-3 py-2 text-sm text-neutral-500" />
                )}
              </div>
            )}

            {/* Display name */}
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Display Name <span className="text-danger-500">*</span>
              </label>
              <input type="text" value={name} onChange={e => setName(e.target.value)} required
                placeholder={`e.g. My ${PROVIDER_LABELS[ptype]} Instance`}
                className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 text-neutral-800 dark:text-neutral-100" />
            </div>

            {/* Connection test — validates reachability + auth + model listing */}
            <div className="rounded-md border border-neutral-200 dark:border-neutral-700 p-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs text-neutral-500 dark:text-neutral-400">
                  Models are discovered automatically from this provider after saving.
                </p>
                {!isEdit && (
                  <button type="button" onClick={testConnection} disabled={testingConn}
                    className="flex-shrink-0 px-3 py-1.5 text-xs font-medium border border-primary-300 text-primary-700 dark:text-primary-300 rounded-md hover:bg-primary-50 disabled:opacity-50 transition-colors">
                    {testingConn ? 'Testing…' : '⚡ Test Connection'}
                  </button>
                )}
              </div>
              {connResult && (
                <p role="status"
                  className={`mt-2 text-xs font-medium ${connResult.ok
                    ? 'text-success-700'
                    : 'text-danger-700'}`}>
                  {connResult.ok ? '✓ ' : '✗ '}{connResult.message}
                </p>
              )}
            </div>

            {/* Base URL — pre-filled from preset, editable for custom endpoints */}
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Base URL
                {baseUrlRequiredFinal && !preset && <span className="text-danger-500 ml-1">*</span>}
                {!baseUrlRequiredFinal && <span className="text-neutral-400 font-normal ml-1">(optional)</span>}
              </label>
              <input type="url" value={baseUrl} onChange={e => setBaseUrl(e.target.value)}
                required={baseUrlRequiredFinal}
                placeholder={preset?.default_base_url || 'https://...'}
                className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary-500 text-neutral-800 dark:text-neutral-100" />
              {preset?.id === 'openai_compatible' && (
                <p className="text-xs text-neutral-400 mt-1">
                  Works with: vLLM, LM Studio, LocalAI, company AI gateways, or any OpenAI-compatible server.
                  Use <code className="font-mono bg-neutral-100 dark:bg-neutral-700 px-1 rounded">host.docker.internal</code> to reach the host machine from Docker.
                </p>
              )}
              {preset && preset.id !== 'openai_compatible' && (
                <p className="text-xs text-neutral-400 mt-1">Pre-filled from the {preset.label} preset — edit only if you use a custom endpoint.</p>
              )}
            </div>

            {/* API key — write only, never pre-filled */}
            {(requiresApiKey || preset?.id === 'openai_compatible') ? (
              <div>
                {isEdit && initial?.has_api_key ? (
                  <>
                    <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                      API Key
                    </label>
                    <div className="flex items-center gap-2">
                      {/* Masked hint from server — at most the last 4 characters */}
                      <span className="flex-1 rounded-md border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-700 px-3 py-2 text-sm text-neutral-400 font-mono">
                        {initial.api_key_masked ?? '••••••••'}
                      </span>
                      <button type="button" onClick={() => setReplaceKey(r => !r)}
                        className="text-xs text-primary-600 hover:underline px-2">
                        {replaceKey ? 'Cancel' : 'Replace'}
                      </button>
                    </div>
                    {replaceKey && (
                      <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)}
                        placeholder="Enter new API key"
                        autoComplete="new-password"
                        className="mt-2 w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 text-neutral-800 dark:text-neutral-100" />
                    )}
                  </>
                ) : (
                  <>
                    <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                      API Key
                      {!requiresApiKey && <span className="text-neutral-400 font-normal ml-1">(optional)</span>}
                    </label>
                    <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)}
                      required={requiresApiKey && !isEdit}
                      placeholder={apiKeyHint}
                      autoComplete="new-password"
                      className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 text-neutral-800 dark:text-neutral-100" />
                    {preset?.api_key_url && (
                      <p className="text-xs mt-1">
                        <a href={preset.api_key_url} target="_blank" rel="noreferrer"
                          className="text-primary-600 hover:underline">Get an API key ↗</a>
                      </p>
                    )}
                    <p className="text-xs text-neutral-400 mt-1">
                      🔒 Stored securely; the API never returns it — only a masked hint.
                    </p>
                  </>
                )}
              </div>
            ) : (
              /* Ollama-style providers: no key needed */
              isEdit && initial?.has_api_key ? (
                <div>
                  <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">API Key</label>
                  <div className="flex items-center gap-2">
                    <span className="flex-1 rounded-md border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-700 px-3 py-2 text-sm text-neutral-400 font-mono">
                      {initial.api_key_masked ?? '••••••••'}
                    </span>
                    <button type="button" onClick={() => setReplaceKey(r => !r)}
                      className="text-xs text-primary-600 hover:underline px-2">
                      {replaceKey ? 'Cancel' : 'Replace'}
                    </button>
                  </div>
                  {replaceKey && (
                    <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)}
                      placeholder="Enter new API key (usually not needed)"
                      autoComplete="new-password"
                      className="mt-2 w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 text-neutral-800 dark:text-neutral-100" />
                  )}
                </div>
              ) : (
                <p className="text-xs text-green-700 bg-green-50 border border-green-200 rounded px-3 py-2">
                  ✓ No API key required
                </p>
              )
            )}

            {/* Description */}
            <div>
              <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Description (optional)</label>
              <input type="text" value={description} onChange={e => setDescription(e.target.value)}
                placeholder="e.g. Company internal AI gateway"
                className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 text-neutral-800 dark:text-neutral-100" />
            </div>

            {/* Capabilities */}
            <div className="flex items-center gap-4 pt-1">
              <label className="flex items-center gap-2 cursor-pointer text-sm text-neutral-700 dark:text-neutral-300">
                <input type="checkbox" checked={supportsEmbed} onChange={e => setSupportsEmbed(e.target.checked)}
                  className="h-4 w-4 rounded border-neutral-300 text-primary-600 focus:ring-primary-500" />
                Supports embeddings
              </label>
              <label className="flex items-center gap-2 cursor-pointer text-sm text-neutral-700 dark:text-neutral-300">
                <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)}
                  className="h-4 w-4 rounded border-neutral-300 text-primary-600 focus:ring-primary-500" />
                Enabled
              </label>
            </div>
          </div>

          <div className="flex justify-end gap-3 p-6 border-t border-neutral-200 dark:border-neutral-700">
            <button type="button" onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-neutral-700 dark:text-neutral-300 border border-neutral-300 dark:border-neutral-600 rounded-md hover:bg-neutral-50">
              Cancel
            </button>
            <button type="submit" disabled={loading || !name.trim()}
              className="px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-md hover:bg-primary-700 disabled:opacity-50">
              {loading ? 'Saving…' : isEdit ? 'Save Changes' : 'Save Provider'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------
// Provider card
// ------------------------------------------------------------------
function ProviderCard({
  provider,
  isAdmin,
  onEdit,
  onDelete,
  onTest,
}: {
  provider: ProviderResponse
  isAdmin: boolean
  onEdit: () => void
  onDelete: () => void
  onTest: () => void
}) {
  return (
    <div className={`bg-white dark:bg-neutral-800 rounded-lg shadow-sm border p-5 transition-all
      ${provider.enabled ? 'border-neutral-200 dark:border-neutral-700' : 'border-neutral-100 dark:border-neutral-800 opacity-60'}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <h3 className="font-semibold text-neutral-800 dark:text-neutral-100 text-sm">{provider.name}</h3>
            <TypeBadge type={provider.provider_type} />
            <span className="text-xs text-neutral-400">{ENV_LABELS[provider.environment]}</span>
            {!provider.enabled && (
              <span className="text-xs bg-neutral-100 text-neutral-500 px-2 py-0.5 rounded-full">disabled</span>
            )}
          </div>
          {provider.base_url && (
            <p className="font-mono text-xs text-neutral-600 dark:text-neutral-400 truncate">{provider.base_url}</p>
          )}
          {/* Legacy pinned model shown only when one was explicitly set */}
          {provider.model_name && (
            <p className="text-xs text-neutral-500 truncate mt-0.5">pinned model: <span className="font-mono">{provider.model_name}</span></p>
          )}
          {provider.description && (
            <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1">{provider.description}</p>
          )}
          <div className="flex gap-3 mt-2 text-xs text-neutral-400 flex-wrap items-center">
            <span className={`px-2 py-0.5 rounded-full font-medium ${
              provider.enabled
                ? 'bg-success-50 text-success-700 border border-success-200'
                : 'bg-neutral-100 text-neutral-500 border border-neutral-200'
            }`}>
              {provider.enabled ? '✓ connected' : 'disabled'}
            </span>
            <span>{provider.model_count} model{provider.model_count === 1 ? '' : 's'}</span>
            {provider.has_api_key && (
              <span title="API key stored — never displayed in full">
                🔑 {provider.api_key_masked ?? '••••••••'}
              </span>
            )}
          </div>
        </div>

        {isAdmin && (
          <div className="flex gap-1 flex-shrink-0">
            <button onClick={onTest}
              className="text-xs px-2 py-1 text-neutral-500 hover:text-primary-600 border border-neutral-200 dark:border-neutral-600 rounded transition-colors"
              title="Test connection">
              Test
            </button>
            <button onClick={onEdit}
              className="text-xs px-2 py-1 text-neutral-500 hover:text-primary-600 border border-neutral-200 dark:border-neutral-600 rounded transition-colors">
              Edit
            </button>
            <button onClick={onDelete}
              className="text-xs px-2 py-1 text-neutral-500 hover:text-danger-600 border border-neutral-200 dark:border-neutral-600 rounded transition-colors">
              ✕
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------
// Main page
// ------------------------------------------------------------------
export default function ProvidersPage() {
  const { user } = useAuthStore()
  const { addToast } = useUIStore()
  const isAdmin = user?.role === 'admin'

  const [providers, setProviders] = useState<ProviderResponse[]>([])
  const [presets, setPresets] = useState<ProviderPreset[]>([])
  const [loading, setLoading] = useState(true)
  // Create flow: null → picker closed; 'pick' → preset grid; ProviderPreset/object → form
  const [showCreate, setShowCreate] = useState<
    null | 'pick' | { form: true; preset: ProviderPreset | null }
  >(null)
  const [editTarget, setEditTarget] = useState<ProviderResponse | null>(null)
  const [testResult, setTestResult] = useState<{ id: string; result: ProviderTestResult } | null>(null)
  const [testing, setTesting] = useState<string | null>(null)

  const load = async () => {
    const [ps, presets] = await Promise.allSettled([
      providersApi.list(),
      providersApi.presets(),
    ])
    if (ps.status === 'fulfilled') setProviders(ps.value)
    if (presets.status === 'fulfilled') setPresets(presets.value)
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const handleCreate = async (data: any) => {
    const p = await providersApi.create(data)
    setProviders(prev => [...prev, p])
    addToast({ type: 'success', title: 'Provider added', message: p.name })
    // Auto-discover models right after saving so the Models page is ready
    try {
      const found = await providersApi.refreshModels(p.id)
      addToast({
        type: 'success', title: 'Models discovered',
        message: `${found.filter(m => m.status === 'available').length} models available`,
      })
      await load()
    } catch {
      addToast({ type: 'warning' as any, title: 'Saved — but discovery failed', message: 'Use "Refresh Models" on the Models page.' } as any)
    }
  }

  const handleUpdate = async (id: string, data: any) => {
    const p = await providersApi.update(id, data)
    setProviders(prev => prev.map(x => x.id === id ? p : x))
    addToast({ type: 'success', title: 'Provider updated' })
  }

  const handleDelete = async (id: string, name: string) => {
    if (!window.confirm(`Delete "${name}"? This cannot be undone.`)) return
    await providersApi.delete(id)
    setProviders(prev => prev.filter(p => p.id !== id))
    addToast({ type: 'info', title: 'Provider deleted' })
  }

  const handleTest = async (id: string) => {
    setTesting(id)
    setTestResult(null)
    try {
      const result = await providersApi.test(id)
      setTestResult({ id, result })
      addToast({
        type: result.success ? 'success' : 'error',
        title: result.success ? 'Connection OK' : 'Connection failed',
        message: result.success
          ? (result.models_found != null ? `${result.models_found} models available · ${result.latency_ms}ms` : `${result.latency_ms}ms`)
          : result.error || 'Unknown error',
      })
    } catch {
      addToast({ type: 'error', title: 'Test failed', message: 'Could not reach provider' })
    } finally {
      setTesting(null)
    }
  }

  // Group by environment
  const local = providers.filter(p => p.environment === 'local')
  const cloud = providers.filter(p => p.environment === 'cloud')
  const custom = providers.filter(p => p.environment === 'custom')

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">LLM Providers</h1>
          <p className="text-sm text-neutral-500 mt-1">
            Configure AI model providers — local, cloud, or custom OpenAI-compatible endpoints
          </p>
        </div>
        {isAdmin && (
          <button onClick={() => setShowCreate('pick')}
            className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700 transition-colors">
            + Add LLM Provider
          </button>
        )}
      </div>

      {/* SIH story banner */}
      <div className="p-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-lg text-sm text-blue-700 dark:text-blue-300">
        <strong>Model-agnostic architecture:</strong> Use a fully local model for data sovereignty,
        a cloud model when permitted, or connect your own internal AI infrastructure via the
        OpenAI-compatible adapter — all through the same interface.
      </div>

      {/* Test result banner */}
      {testResult && (
        <div className={`p-3 rounded-lg border text-sm flex items-center justify-between
          ${testResult.result.success
            ? 'bg-success-50 border-success-200 text-success-800'
            : 'bg-danger-50 border-danger-200 text-danger-700'}`}>
          <span>
            {testResult.result.success
              ? `✓ Connected to ${testResult.result.provider}` +
                (testResult.result.models_found != null
                  ? ` — ${testResult.result.models_found} model${testResult.result.models_found === 1 ? '' : 's'} available`
                  : '') +
                ` (${testResult.result.latency_ms}ms)`
              : `✗ ${testResult.result.error || 'Connection failed'}`
            }
          </span>
          <button onClick={() => setTestResult(null)} className="text-current opacity-60 hover:opacity-100 ml-2">✕</button>
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[...Array(2)].map((_, i) => <div key={i} className="bg-neutral-100 dark:bg-neutral-800 rounded-lg h-28 animate-pulse" />)}
        </div>
      ) : providers.length === 0 ? (
        <div className="flex flex-col items-center justify-center min-h-48 text-center">
          <div className="text-4xl mb-3" aria-hidden="true">🤖</div>
          <p className="text-neutral-600 dark:text-neutral-400 font-medium">No providers configured</p>
          {isAdmin && (
            <button onClick={() => setShowCreate('pick')}
              className="mt-3 px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700">
              + Add First Provider
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-6">
          {local.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-neutral-500 uppercase tracking-wider mb-3">🖥 Local</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {local.map(p => (
                  <ProviderCard key={p.id} provider={p} isAdmin={isAdmin}
                    onEdit={() => setEditTarget(p)}
                    onDelete={() => handleDelete(p.id, p.name)}
                    onTest={() => handleTest(p.id)} />
                ))}
              </div>
            </div>
          )}
          {cloud.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-neutral-500 uppercase tracking-wider mb-3">☁️ Cloud</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {cloud.map(p => (
                  <ProviderCard key={p.id} provider={p} isAdmin={isAdmin}
                    onEdit={() => setEditTarget(p)}
                    onDelete={() => handleDelete(p.id, p.name)}
                    onTest={() => handleTest(p.id)} />
                ))}
              </div>
            </div>
          )}
          {custom.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-neutral-500 uppercase tracking-wider mb-3">⚙️ Custom / Compatible</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {custom.map(p => (
                  <ProviderCard key={p.id} provider={p} isAdmin={isAdmin}
                    onEdit={() => setEditTarget(p)}
                    onDelete={() => handleDelete(p.id, p.name)}
                    onTest={() => handleTest(p.id)} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Step 1: preset picker */}
      {showCreate === 'pick' && (
        <PresetPicker
          presets={presets}
          onPick={(preset) => setShowCreate({ form: true, preset })}
          onCustom={() => setShowCreate({ form: true, preset: null })}
          onClose={() => setShowCreate(null)}
        />
      )}

      {/* Step 2: preset-aware form */}
      {showCreate && showCreate !== 'pick' && (
        <ProviderForm
          preset={showCreate.preset}
          onClose={() => setShowCreate(null)}
          onSave={handleCreate}
        />
      )}

      {/* Edit modal */}
      {editTarget && (
        <ProviderForm
          initial={editTarget}
          onClose={() => setEditTarget(null)}
          onSave={(data) => handleUpdate(editTarget.id, data)}
        />
      )}
    </div>
  )
}
