/**
 * Plugins page — packaged capability bundles.
 * A disabled plugin disables every tool it provides (enforced server-side).
 */
import { useEffect, useState } from 'react'
import { pluginsApi, PluginInfo } from '../api/tools'
import { useAuthStore } from '../stores/authStore'
import { useUIStore } from '../stores/uiStore'

export default function PluginsPage() {
  const { user } = useAuthStore()
  const { addToast } = useUIStore()
  const isAdmin = user?.role === 'admin'
  const [plugins, setPlugins] = useState<PluginInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)

  const load = async () => {
    try { setPlugins(await pluginsApi.list()) } catch { setPlugins([]) }
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  const toggle = async (p: PluginInfo) => {
    if (!isAdmin || p.id === 'core-utilities') return   // core always on
    setBusy(p.id)
    try {
      await (p.enabled ? pluginsApi.disable(p.id) : pluginsApi.enable(p.id))
      await load()
      addToast({ type: 'success', title: `${p.name} ${p.enabled ? 'disabled' : 'enabled'}` })
    } catch {
      addToast({ type: 'error', title: 'Update failed' })
    } finally {
      setBusy(null)
    }
  }

  const testPlugin = async (p: PluginInfo) => {
    setBusy(p.id)
    try {
      const r = await pluginsApi.test(p.id)
      addToast({
        type: r.success ? 'success' : 'error',
        title: `${p.name}: ${r.success ? 'OK' : 'unavailable'}`,
        message: r.note ?? '',
      })
    } finally { setBusy(null) }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">Plugins</h1>
        <p className="text-sm text-neutral-500 mt-1">
          Packaged capabilities — disabling a plugin removes its tools from the Agent
        </p>
      </div>

      {loading ? (
        <div className="space-y-4">
          {[...Array(3)].map((_, i) => <div key={i} className="bg-neutral-100 dark:bg-neutral-800 rounded-lg h-36 animate-pulse" />)}
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {plugins.map(p => (
            <div key={p.id} className={`bg-white dark:bg-neutral-800 rounded-lg border p-5
              ${p.enabled ? 'border-neutral-200 dark:border-neutral-700'
                          : 'border-dashed border-neutral-300 dark:border-neutral-600 opacity-75'}`}>
              <div className="flex items-start justify-between mb-2">
                <div>
                  <h3 className="font-semibold text-sm text-neutral-800 dark:text-neutral-100">{p.name}</h3>
                  <span className="text-xs text-neutral-400">v{p.version} · {p.author}</span>
                </div>
                <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                  p.enabled ? 'bg-success-100 text-success-700'
                            : 'bg-neutral-100 text-neutral-500'}`}>
                  {p.enabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>

              <p className="text-xs text-neutral-500 mb-3">{p.description}</p>

              <p className="text-xs font-medium text-neutral-600 dark:text-neutral-300 mb-1">Provides:</p>
              <ul className="text-xs text-neutral-500 space-y-0.5 mb-3">
                {p.tools_detail.map(t => (
                  <li key={t.name}>
                    {t.enabled ? '✓' : '✗'} <span className="font-mono">{t.name}</span>
                  </li>
                ))}
              </ul>

              {p.permissions.length > 0 && (
                <div className="flex flex-wrap gap-1 mb-3">
                  {p.permissions.map(perm => (
                    <span key={perm} className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-600">
                      ⚠ {perm}
                    </span>
                  ))}
                </div>
              )}

              <div className="flex gap-1.5 flex-wrap">
                {isAdmin && p.id !== 'core-utilities' && (
                  <button onClick={() => toggle(p)} disabled={busy === p.id}
                    className={`text-xs px-2 py-1 rounded border transition-colors disabled:opacity-40 ${
                      p.enabled
                        ? 'border-neutral-300 text-neutral-600 hover:bg-danger-50 hover:border-danger-300 dark:border-neutral-600 dark:text-neutral-300'
                        : 'bg-primary-600 text-white border-primary-600 hover:bg-primary-700'
                    }`}>
                    {busy === p.id ? '…' : p.enabled ? 'Disable' : 'Enable'}
                  </button>
                )}
                <button onClick={() => testPlugin(p)} disabled={busy === p.id}
                  className="text-xs px-2 py-1 rounded border border-neutral-300 text-neutral-600 hover:bg-neutral-50 disabled:opacity-40 dark:border-neutral-600 dark:text-neutral-300">
                  Test
                </button>
                {!isAdmin && !p.enabled && (
                  <span className="text-xs text-neutral-400 self-center">Ask an admin to enable</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
