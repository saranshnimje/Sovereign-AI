import { useEffect, useState } from 'react'
import { auditApi, AuditLogItem } from '../api/settings'
import { formatIST, formatISTDate } from '../utils/dates'
import { useUIStore } from '../stores/uiStore'

const EVENT_TYPES = ['auth', 'model', 'document', 'rag', 'agent', 'tool', 'sandbox', 'approval', 'config', 'error', 'security']
const OUTCOMES = ['success', 'failure', 'pending']
const PAGE_SIZE = 50

function OutcomeBadge({ outcome }: { outcome: string }) {
  const cfg: Record<string, string> = {
    success: 'bg-green-900/30 text-green-400', failure: 'bg-red-900/30 text-red-400', pending: 'bg-yellow-900/30 text-yellow-400',
  }
  return <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cfg[outcome] || 'bg-neutral-800 text-neutral-400'}`}>{outcome}</span>
}

export default function AuditPage() {
  const { addToast } = useUIStore()
  const [eventType, setEventType] = useState('')
  const [outcome, setOutcome] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [ipFilter, setIpFilter] = useState('')
  const [offset, setOffset] = useState(0)
  const [entries, setEntries] = useState<AuditLogItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [verifyResult, setVerifyResult] = useState<{ verified: boolean; entries_checked: number; message: string } | null>(null)
  const [verifying, setVerifying] = useState(false)
  const [selectedEntry, setSelectedEntry] = useState<AuditLogItem | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const data = await auditApi.list({ event_type: eventType || undefined, outcome: outcome || undefined, ip_address: ipFilter || undefined, start_date: startDate || undefined, end_date: endDate || undefined, limit: PAGE_SIZE, offset })
      setEntries(data.items); setTotal(data.total)
    } catch {}
    setLoading(false)
  }
  useEffect(() => { load() }, [eventType, outcome, startDate, endDate, offset])

  const handleVerify = async () => {
    setVerifying(true)
    try { const r = await auditApi.verify(); setVerifyResult(r) }
    catch { addToast({ type: 'error', title: 'Verification failed' }) }
    setVerifying(false)
  }
  const handleExport = (fmt: 'csv' | 'json') => { window.open(auditApi.exportUrl(fmt, { event_type: eventType || undefined, outcome: outcome || undefined }), '_blank') }

  const totalPages = Math.ceil(total / PAGE_SIZE)
  const page = Math.floor(offset / PAGE_SIZE) + 1
  const inputCls = "w-full text-sm border border-green-900/40 rounded-lg px-2 py-1.5 bg-[#050e05] text-neutral-200 focus:outline-none focus:ring-2 focus:ring-green-500"

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Audit Log</h1>
          <p className="text-sm text-neutral-400 mt-1">Tamper-evident hash-chained event log · {total.toLocaleString()} total events</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleVerify} disabled={verifying}
            className="px-3 py-1.5 text-sm font-medium border border-green-800/40 text-neutral-300 rounded-lg hover:bg-green-900/20 disabled:opacity-50">
            {verifying ? '…' : '🔐 Verify Integrity'}
          </button>
          <button onClick={() => handleExport('csv')} className="px-3 py-1.5 text-sm font-medium border border-green-800/40 text-neutral-300 rounded-lg hover:bg-green-900/20">↓ CSV</button>
          <button onClick={() => handleExport('json')} className="px-3 py-1.5 text-sm font-medium border border-green-800/40 text-neutral-300 rounded-lg hover:bg-green-900/20">↓ JSON</button>
        </div>
      </div>

      {verifyResult && (
        <div className={`p-3 rounded-lg border text-sm font-medium ${
          verifyResult.verified ? 'bg-green-900/20 border-green-800/40 text-green-400' : 'bg-red-900/20 border-red-800/40 text-red-400'
        }`} role="status">
          {verifyResult.verified ? '✓' : '✗'} {verifyResult.message}
        </div>
      )}

      <div className="bg-[#0a1a0a] border border-green-900/40 rounded-xl p-4">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div>
            <label className="block text-xs font-medium text-neutral-500 mb-1">Event Type</label>
            <select value={eventType} onChange={e => { setEventType(e.target.value); setOffset(0) }} className={inputCls}>
              <option value="">All types</option>
              {EVENT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-neutral-500 mb-1">Outcome</label>
            <select value={outcome} onChange={e => { setOutcome(e.target.value); setOffset(0) }} className={inputCls}>
              <option value="">All outcomes</option>
              {OUTCOMES.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-neutral-500 mb-1">From</label>
            <input type="datetime-local" value={startDate} onChange={e => { setStartDate(e.target.value); setOffset(0) }} className={inputCls} />
          </div>
          <div>
            <label className="block text-xs font-medium text-neutral-500 mb-1">To</label>
            <input type="datetime-local" value={endDate} onChange={e => { setEndDate(e.target.value); setOffset(0) }} className={inputCls} />
          </div>
          <div>
            <label className="block text-xs font-medium text-neutral-500 mb-1">IP Address</label>
            <input type="text" value={ipFilter} onChange={e => { setIpFilter(e.target.value); setOffset(0) }} placeholder="e.g. 192.168." className={inputCls + ' font-mono'} />
          </div>
        </div>
      </div>

      <div className="bg-[#0a1a0a] border border-green-900/40 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          {loading ? (
            <div className="flex justify-center py-12">
              <div className="animate-spin h-6 w-6 border-2 border-green-500 border-t-transparent rounded-full" />
            </div>
          ) : entries.length === 0 ? (
            <div className="text-center py-12 text-neutral-500">No audit events match your filters</div>
          ) : (
            <table className="w-full text-sm" aria-label="Audit log entries">
              <thead>
                <tr className="bg-[#050e05] text-left border-b border-green-900/30">
                  <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase">#</th>
                  <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase">Timestamp</th>
                  <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase">Type</th>
                  <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase">Action</th>
                  <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase">Outcome</th>
                  <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase">Resource</th>
                  <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase">IP</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-green-900/20">
                {entries.map(e => (
                  <tr key={e.id} onClick={() => setSelectedEntry(selectedEntry?.id === e.id ? null : e)}
                    className="hover:bg-green-900/10 cursor-pointer transition-colors">
                    <td className="px-4 py-3 text-xs text-neutral-500 font-mono">{e.sequence_num}</td>
                    <td className="px-4 py-3 text-xs text-neutral-400">{formatIST(e.timestamp)}</td>
                    <td className="px-4 py-3"><span className="text-xs font-mono text-green-400">{e.event_type}</span></td>
                    <td className="px-4 py-3 text-xs text-neutral-300 font-mono">{e.action}</td>
                    <td className="px-4 py-3"><OutcomeBadge outcome={e.outcome} /></td>
                    <td className="px-4 py-3 text-xs text-neutral-500">{e.resource_type || '—'}</td>
                    <td className="px-4 py-3 text-xs font-mono text-neutral-500">{e.ip_address || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {selectedEntry && (
          <div className="border-t border-green-900/30 p-4 bg-[#050e05]">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-neutral-300">Entry #{selectedEntry.sequence_num}</h3>
              <button onClick={() => setSelectedEntry(null)} className="text-xs text-neutral-500 hover:text-neutral-300">✕ Close</button>
            </div>
            <pre className="text-xs bg-[#0a1a0a] text-green-400 rounded-lg p-3 overflow-x-auto border border-green-900/20">{JSON.stringify(selectedEntry, null, 2)}</pre>
          </div>
        )}

        {total > PAGE_SIZE && (
          <div className="px-4 py-3 border-t border-green-900/30 flex items-center justify-between text-sm">
            <span className="text-neutral-500">Showing {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total.toLocaleString()}</span>
            <div className="flex gap-2">
              <button onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} disabled={page === 1}
                className="px-3 py-1 border border-green-900/40 rounded-lg disabled:opacity-40 hover:bg-green-900/20 text-neutral-400">← Prev</button>
              <span className="px-3 py-1 text-neutral-500">Page {page} / {totalPages}</span>
              <button onClick={() => setOffset(offset + PAGE_SIZE)} disabled={page >= totalPages}
                className="px-3 py-1 border border-green-900/40 rounded-lg disabled:opacity-40 hover:bg-green-900/20 text-neutral-400">Next →</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
