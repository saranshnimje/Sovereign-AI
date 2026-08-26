/**
 * Tools page — manage agent tools grouped by category.
 * Admin: enable/disable. Any user: view + run safe test probes.
 */
import { useEffect, useMemo, useState } from 'react'
import { toolsApi, ToolInfo } from '../api/tools'
import { useAuthStore } from '../stores/authStore'
import { useUIStore } from '../stores/uiStore'

const CATEGORY_META: Record<string, { label: string; icon: string }> = {
  web: { label: 'Web', icon: '🌐' },
  files: { label: 'Files', icon: '📄' },
  utilities: { label: 'Utilities', icon: '🧮' },
  knowledge: { label: 'AI / Knowledge', icon: '📚' },
  agent: { label: 'Agent', icon: '🤖' },
  advanced: { label: 'Advanced', icon: '⚙️' },
}

const RISK_COLORS: Record<string, string> = {
  low: 'bg-green-100 text-green-700',
  medium: 'bg-yellow-100 text-yellow-700',
  high: 'bg-orange-100 text-orange-700',
  critical: 'bg-red-100 text-red-700',
}

function ToolCard({ tool, isAdmin, onChanged }: {
  tool: ToolInfo
  isAdmin: boolean
  onChanged: () => void
}) {
  const { addToast } = useUIStore()
  const [busy, setBusy] = useState(false)

  const toggle = async () => {
    setBusy(true)
    try {
      await (tool.enabled ? toolsApi.disable(tool.name) : toolsApi.enable(tool.name))
      onChanged()
    } catch {
      addToast({ type: 'error', title: 'Update failed' })
    } finally {
      setBusy(false)
    }
  }

  const test = async () => {
    setBusy(true)
    try {
      const r = await toolsApi.test(tool.name)
      addToast({
        type: r.success ? 'success' : 'error',
        title: `${tool.name}: ${r.success ? 'probe OK' : 'probe failed'}`,
        message: r.latency_ms != null ? `${r.latency_ms}ms` : (r.error || r.note || ''),
      })
    } catch {
      addToast({ type: 'error', title: 'Test failed' })
    } finally {
      setBusy(false)
    }
  }

  const meta = CATEGORY_META[tool.category] ?? { label: tool.category, icon: '🔧' }

  return (
    <div className={`bg-white dark:bg-neutral-800 rounded-lg border p-4 transition-all
      ${tool.enabled ? 'border-neutral-200 dark:border-neutral-700'
                      : 'border-dashed border-neutral-300 dark:border-neutral-600 opacity-70'}`}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="min-w-0">
          <h3 className="font-mono text-sm font-semibold text-neutral-800 dark:text-neutral-100 truncate">
            {meta.icon} {tool.name}
          </h3>
          <p className="text-xs text-neutral-500 mt-0.5">{tool.description}</p>
        </div>
        <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium flex-shrink-0 ${
          tool.enabled ? 'bg-success-100 text-success-700'
                       : 'bg-neutral-100 text-neutral-500'}`}>
          {tool.enabled ? 'Enabled' : 'Disabled'}
        </span>
      </div>

      <div className="flex flex-wrap gap-1 mb-3 text-[10px]">
        <span className={`px-1.5 py-0.5 rounded ${RISK_COLORS[tool.risk_level]}`}>
          risk: {tool.risk_level}
        </span>
        {tool.permissions.map(p => (
          <span key={p} className="px-1.5 py-0.5 rounded bg-blue-50 text-blue-600">⚠ {p}</span>
        ))}
        <span className="px-1.5 py-0.5 rounded bg-neutral-100 text-neutral-500">v{tool.version}</span>
        {tool.provided_by && (
          <span className="px-1.5 py-0.5 rounded bg-purple-50 text-purple-600">
            plugin: {tool.provided_by}
          </span>
        )}
      </div>

      <div className="flex gap-1.5 flex-wrap">
        {isAdmin && (
          <button onClick={toggle} disabled={busy}
            className={`text-xs px-2 py-1 rounded border transition-colors disabled:opacity-40 ${
              tool.enabled
                ? 'border-neutral-300 text-neutral-600 hover:bg-danger-50 hover:border-danger-300 dark:border-neutral-600 dark:text-neutral-300'
                : 'bg-primary-600 text-white border-primary-600 hover:bg-primary-700'
            }`}>
            {tool.enabled ? 'Disable' : 'Enable'}
          </button>
        )}
        <button onClick={test} disabled={busy || !tool.enabled}
          className="text-xs px-2 py-1 rounded border border-neutral-300 text-neutral-600 hover:bg-neutral-50 disabled:opacity-40 dark:border-neutral-600 dark:text-neutral-300">
          Test
        </button>
      </div>
    </div>
  )
}

export default function ToolsPage() {
  const { user } = useAuthStore()
  const isAdmin = user?.role === 'admin'
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [loading, setLoading] = useState(true)

  const load = async () => {
    try { setTools(await toolsApi.list()) } catch { setTools([]) }
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  const grouped = useMemo(() => {
    const g: Record<string, ToolInfo[]> = {}
    for (const t of tools) (g[t.category] = g[t.category] ?? []).push(t)
    return g
  }, [tools])

  const enabledCount = tools.filter(t => t.enabled).length

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">Tools</h1>
          <p className="text-sm text-neutral-500 mt-1">
            Actions the AI Agent can perform — permissions enforced server-side
          </p>
        </div>
        <span className="text-sm text-neutral-500">
          {enabledCount}/{tools.length} enabled
        </span>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => <div key={i} className="bg-neutral-100 dark:bg-neutral-800 rounded-lg h-32 animate-pulse" />)}
        </div>
      ) : Object.keys(grouped).sort().map(cat => (
        <section key={cat}>
          <h2 className="text-sm font-semibold text-neutral-500 uppercase tracking-wider mb-3">
            {CATEGORY_META[cat]?.icon ?? '🔧'} {CATEGORY_META[cat]?.label ?? cat}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {grouped[cat].map(t => (
              <ToolCard key={t.name} tool={t} isAdmin={isAdmin} onChanged={load} />
            ))}
          </div>
        </section>
      ))}

      {!loading && tools.length === 0 && (
        <p className="text-center text-neutral-400 py-12">No tools registered.</p>
      )}
    </div>
  )
}
