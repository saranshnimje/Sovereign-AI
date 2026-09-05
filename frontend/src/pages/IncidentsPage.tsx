import { useEffect, useState } from 'react'
import { incidentsApi, Incident } from '../api/incidents'
import { useUIStore } from '../stores/uiStore'
import Badge from '../components/ui/Badge'

const STATUS_COLORS: Record<string, 'success' | 'warning' | 'danger' | 'info'> = {
  open: 'danger', investigating: 'warning', resolved: 'success', closed: 'info',
}

export default function IncidentsPage() {
  const { addToast } = useUIStore()
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null)
  const [statusFilter, setStatusFilter] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newMachine, setNewMachine] = useState('')
  const [investigating, setInvestigating] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const data = await incidentsApi.list({ status: statusFilter || undefined })
      setIncidents(data.items); setTotal(data.total)
    } catch { /* ignore */ }
    setLoading(false)
  }
  useEffect(() => { load() }, [statusFilter])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const inc = await incidentsApi.create({ title: newTitle, machine: newMachine || undefined })
      setIncidents(prev => [inc, ...prev])
      setShowCreate(false); setNewTitle(''); setNewMachine('')
      addToast({ type: 'success', title: 'Incident created' })
    } catch { addToast({ type: 'error', title: 'Create failed' }) }
  }

  const handleInvestigate = async (inc: Incident) => {
    setInvestigating(true)
    try {
      const updated = await incidentsApi.investigate(inc.id)
      setIncidents(prev => prev.map(i => i.id === updated.id ? updated : i))
      setSelectedIncident(updated)
      addToast({ type: 'success', title: 'Investigation complete' })
    } catch { addToast({ type: 'error', title: 'Investigation failed' }) }
    setInvestigating(false)
  }

  const timeAgo = (ts: string) => {
    const diff = Date.now() - new Date(ts).getTime()
    if (diff < 60000) return 'just now'
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`
    return `${Math.floor(diff / 86400000)}d ago`
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-lg md:text-2xl font-bold text-white">Incidents</h1>
          <p className="text-xs md:text-sm text-neutral-400 mt-1">Track, investigate, and manage incidents with AI analysis.</p>
        </div>
        <button onClick={() => setShowCreate(true)} className="px-3 md:px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-medium hover:bg-cyan-500">
          + New Incident
        </button>
      </div>

      <div className="flex gap-2 flex-wrap">
        {['', 'open', 'investigating', 'resolved', 'closed'].map(s => (
          <button key={s} onClick={() => setStatusFilter(s)}
            className={`px-3 py-1.5 text-xs rounded-lg border transition-colors ${statusFilter === s ? 'bg-cyan-600 text-white border-cyan-600' : 'border-surface-border text-neutral-400 hover:bg-surface-muted'}`}>
            {s || 'All'}
          </button>
        ))}
      </div>

      {showCreate && (
        <div className="bg-surface-raised border border-surface-border rounded-xl p-6">
          <h2 className="text-lg font-semibold text-white mb-4">New Incident</h2>
          <form onSubmit={handleCreate} className="space-y-4">
            <input type="text" value={newTitle} onChange={e => setNewTitle(e.target.value)} required placeholder="Incident title"
              className="w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:ring-2 focus:ring-cyan-500" />
            <input type="text" value={newMachine} onChange={e => setNewMachine(e.target.value)} placeholder="Machine/Equipment (optional)"
              className="w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:ring-2 focus:ring-cyan-500" />
            <div className="flex gap-2">
              <button type="submit" disabled={!newTitle.trim()} className="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-medium hover:bg-cyan-500 disabled:opacity-50">Create</button>
              <button type="button" onClick={() => setShowCreate(false)} className="px-4 py-2 border border-surface-border text-neutral-300 rounded-lg text-sm hover:bg-surface-muted">Cancel</button>
            </div>
          </form>
        </div>
      )}

      {loading ? (
        <div className="space-y-3">{[...Array(3)].map((_, i) => <div key={i} className="skeleton h-20" />)}</div>
      ) : incidents.length === 0 ? (
        <div className="bg-surface-raised border border-surface-border rounded-xl p-12 text-center">
          <div className="w-16 h-16 rounded-2xl bg-cyan-500/10 flex items-center justify-center text-3xl mx-auto mb-4">
            <svg className="w-8 h-8 text-cyan-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126z" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-white mb-2">No Incidents</h3>
          <p className="text-sm text-neutral-400">No incidents have been reported yet.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {incidents.map(inc => (
            <div key={inc.id} className="bg-surface-raised border border-surface-border rounded-xl p-4 hover:border-cyan-700/50 transition-all cursor-pointer"
              onClick={() => setSelectedIncident(selectedIncident?.id === inc.id ? null : inc)}>
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="text-sm font-medium text-neutral-200">{inc.title}</h3>
                    <Badge variant={STATUS_COLORS[inc.status] || 'default'} size="sm">{inc.status}</Badge>
                  </div>
                  <div className="flex gap-4 text-[11px] text-neutral-500">
                    {inc.machine && <span>Machine: {inc.machine}</span>}
                    <span>{timeAgo(inc.created_at)}</span>
                  </div>
                </div>
                {inc.status !== 'resolved' && inc.status !== 'closed' && (
                  <button onClick={(e) => { e.stopPropagation(); handleInvestigate(inc) }} disabled={investigating}
                    className="text-xs px-3 py-1.5 border border-cyan-600/50 text-cyan-400 rounded-lg hover:bg-cyan-500/10 disabled:opacity-50">
                    {investigating ? 'Investigating...' : 'Investigate'}
                  </button>
                )}
              </div>
              {selectedIncident?.id === inc.id && inc.ai_analysis && (
                <div className="mt-4 p-4 bg-surface-overlay rounded-lg border border-surface-border">
                  <h4 className="text-xs font-semibold text-cyan-400 mb-2">AI Analysis</h4>
                  <p className="text-xs text-neutral-300 whitespace-pre-wrap">{inc.ai_analysis}</p>
                  {inc.recommendation_action && (
                    <div className="mt-3 p-2 bg-warning-500/10 border border-warning-500/30 rounded">
                      <p className="text-xs text-warning-500 font-medium">Recommendation: {inc.recommendation_action}</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
