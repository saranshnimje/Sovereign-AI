import { useEffect, useState } from 'react'
import { toolsApi, Tool, Plugin } from '../api/tools'
import { useUIStore } from '../stores/uiStore'
import Badge from '../components/ui/Badge'

const RISK_COLORS: Record<string, 'success' | 'warning' | 'danger' | 'info'> = {
  LOW: 'success', MEDIUM: 'warning', HIGH: 'danger', CRITICAL: 'danger',
}

export default function ToolsPage() {
  const { addToast } = useUIStore()
  const [tools, setTools] = useState<Tool[]>([])
  const [plugins, setPlugins] = useState<Plugin[]>([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<'tools' | 'plugins'>('tools')

  useEffect(() => {
    const load = async () => {
      const [t, p] = await Promise.allSettled([toolsApi.listTools(), toolsApi.listPlugins()])
      if (t.status === 'fulfilled') setTools(t.value)
      if (p.status === 'fulfilled') setPlugins(p.value)
      setLoading(false)
    }
    load()
  }, [])

  const toggleTool = async (tool: Tool) => {
    try {
      const updated = await toolsApi.setToolEnabled(tool.name, !tool.enabled)
      setTools(prev => prev.map(t => t.name === updated.name ? updated : t))
      addToast({ type: 'success', title: `${tool.name} ${updated.enabled ? 'enabled' : 'disabled'}` })
    } catch { addToast({ type: 'error', title: 'Failed to update tool' }) }
  }

  const togglePlugin = async (plugin: Plugin) => {
    try {
      const updated = await toolsApi.setPluginEnabled(plugin.id, !plugin.enabled)
      setPlugins(prev => prev.map(p => p.id === updated.id ? updated : p))
      addToast({ type: 'success', title: `${plugin.name} ${updated.enabled ? 'enabled' : 'disabled'}` })
    } catch { addToast({ type: 'error', title: 'Failed to update plugin' }) }
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-white">Tools</h1>
        <p className="text-sm text-neutral-400 mt-1">Manage tools, permissions, and approval requirements for AI agents.</p>
      </div>

      <div className="flex gap-2">
        <button onClick={() => setTab('tools')}
          className={`px-4 py-2 text-sm rounded-lg border transition-colors ${tab === 'tools' ? 'bg-cyan-600 text-white border-cyan-600' : 'border-surface-border text-neutral-400 hover:bg-surface-muted'}`}>
          Tools ({tools.length})
        </button>
        <button onClick={() => setTab('plugins')}
          className={`px-4 py-2 text-sm rounded-lg border transition-colors ${tab === 'plugins' ? 'bg-cyan-600 text-white border-cyan-600' : 'border-surface-border text-neutral-400 hover:bg-surface-muted'}`}>
          Plugins ({plugins.length})
        </button>
      </div>

      {loading ? (
        <div className="space-y-3">{[...Array(5)].map((_, i) => <div key={i} className="skeleton h-20" />)}</div>
      ) : tab === 'tools' ? (
        tools.length === 0 ? (
          <div className="bg-surface-raised border border-surface-border rounded-xl p-12 text-center">
            <h3 className="text-lg font-semibold text-white mb-2">No Tools Available</h3>
            <p className="text-sm text-neutral-400">Tools will appear here when configured in the system.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {tools.map(tool => (
              <div key={tool.name} className="bg-surface-raised border border-surface-border rounded-xl p-4 flex items-center justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="text-sm font-mono font-medium text-neutral-200">{tool.name}</h3>
                    <Badge variant={RISK_COLORS[tool.risk_level] || 'default'} size="sm">{tool.risk_level}</Badge>
                    <span className="text-[10px] text-neutral-500 bg-surface-overlay px-2 py-0.5 rounded">{tool.category}</span>
                  </div>
                  <p className="text-xs text-neutral-400 truncate">{tool.description}</p>
                  <p className="text-[10px] text-neutral-500 mt-1">Required role: {tool.required_role}</p>
                </div>
                <button onClick={() => toggleTool(tool)}
                  className={`px-3 py-1.5 text-xs rounded-lg border transition-colors ${tool.enabled ? 'bg-cyan-600 text-white border-cyan-600' : 'border-surface-border text-neutral-400 hover:bg-surface-muted'}`}>
                  {tool.enabled ? 'Enabled' : 'Disabled'}
                </button>
              </div>
            ))}
          </div>
        )
      ) : (
        plugins.length === 0 ? (
          <div className="bg-surface-raised border border-surface-border rounded-xl p-12 text-center">
            <h3 className="text-lg font-semibold text-white mb-2">No Plugins Available</h3>
            <p className="text-sm text-neutral-400">Plugins will appear here when installed.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {plugins.map(plugin => (
              <div key={plugin.id} className="bg-surface-raised border border-surface-border rounded-xl p-4 flex items-center justify-between">
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-medium text-neutral-200">{plugin.name}</h3>
                  <p className="text-xs text-neutral-400 truncate">{plugin.description}</p>
                </div>
                <button onClick={() => togglePlugin(plugin)}
                  className={`px-3 py-1.5 text-xs rounded-lg border transition-colors ${plugin.enabled ? 'bg-cyan-600 text-white border-cyan-600' : 'border-surface-border text-neutral-400 hover:bg-surface-muted'}`}>
                  {plugin.enabled ? 'Enabled' : 'Disabled'}
                </button>
              </div>
            ))}
          </div>
        )
      )}
    </div>
  )
}
