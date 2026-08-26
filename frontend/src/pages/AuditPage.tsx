/**
 * Audit Log page — filter, paginate, verify integrity, export.
 * Admin-only.
 */
import { useEffect, useState } from 'react'
import { auditApi, AuditLogItem } from '../api/settings'
import { formatIST, formatISTDate } from '../utils/dates'
import { useUIStore } from '../stores/uiStore'

const EVENT_TYPES = ['auth', 'model', 'document', 'rag', 'agent', 'tool', 'sandbox', 'approval', 'config', 'error', 'security']
const OUTCOMES = ['success', 'failure', 'pending']
const PAGE_SIZE = 50

function OutcomeBadge({ outcome }: { outcome: string }) {
  const cfg: Record<string, string> = {
    success: 'bg-success-100 text-success-700',
    failure: 'bg-danger-100 text-danger-600',
    pending: 'bg-yellow-100 text-yellow-700',
  }
  return <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cfg[outcome] || 'bg-neutral-100 text-neutral-600'}`}>{outcome}</span>
}

function VerifyBanner({ result }: { result: { verified: boolean; entries_checked: number; message: string } | null }) {
  if (!result) return null
  return (
    <div className={`p-3 rounded-lg border text-sm font-medium ${
      result.verified
        ? 'bg-success-50 border-success-200 text-success-800'
        : 'bg-danger-50 border-danger-200 text-danger-700'
    }`} role="status">
      {result.verified ? '✓' : '✗'} {result.message}
    </div>
  )
}

export default function AuditPage() {
  const { addToast } = useUIStore()

  // Filters
  const [eventType, setEventType] = useState('')
  const [outcome, setOutcome] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [ipFilter, setIpFilter] = useState('')
  const [offset, setOffset] = useState(0)

  // Data
  const [entries, setEntries] = useState<AuditLogItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)

  // Verify
  const [verifyResult, setVerifyResult] = useState<{
    verified: boolean; entries_checked: number; first_error_at_sequence: number | null; message: string
  } | null>(null)
  const [verifying, setVerifying] = useState(false)

  const [selectedEntry, setSelectedEntry] = useState<AuditLogItem | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const data = await auditApi.list({
        event_type: eventType || undefined,
        outcome: outcome || undefined,
        ip_address: ipFilter || undefined,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        limit: PAGE_SIZE,
        offset,
      })
      setEntries(data.items)
      setTotal(data.total)
    } catch { /* show empty */ }
    setLoading(false)
  }

  useEffect(() => { load() }, [eventType, outcome, startDate, endDate, offset])

  const handleVerify = async () => {
    setVerifying(true)
    try {
      const r = await auditApi.verify()
      setVerifyResult(r)
    } catch {
      addToast({ type: 'error', title: 'Verification failed', message: 'Could not reach server' })
    }
    setVerifying(false)
  }

  const handleExport = (format: 'csv' | 'json') => {
    const url = auditApi.exportUrl(format, {
      event_type: eventType || undefined,
      outcome: outcome || undefined,
    })
    window.open(url, '_blank')
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)
  const page = Math.floor(offset / PAGE_SIZE) + 1

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">Audit Log</h1>
          <p className="text-sm text-neutral-500 mt-1">
            Tamper-evident hash-chained event log · {total.toLocaleString()} total events
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleVerify} disabled={verifying}
            className="px-3 py-1.5 text-sm font-medium border border-neutral-300 dark:border-neutral-600 text-neutral-700 dark:text-neutral-300 rounded-md hover:bg-neutral-50 disabled:opacity-50">
            {verifying ? '…' : '🔐 Verify Integrity'}
          </button>
          <button onClick={() => handleExport('csv')}
            className="px-3 py-1.5 text-sm font-medium border border-neutral-300 dark:border-neutral-600 text-neutral-700 dark:text-neutral-300 rounded-md hover:bg-neutral-50">
            ↓ CSV
          </button>
          <button onClick={() => handleExport('json')}
            className="px-3 py-1.5 text-sm font-medium border border-neutral-300 dark:border-neutral-600 text-neutral-700 dark:text-neutral-300 rounded-md hover:bg-neutral-50">
            ↓ JSON
          </button>
        </div>
      </div>

      {/* Verify result */}
      <VerifyBanner result={verifyResult} />

      {/* Filters */}
      <div className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-4">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div>
            <label className="block text-xs font-medium text-neutral-500 mb-1">Event Type</label>
            <select value={eventType} onChange={e => { setEventType(e.target.value); setOffset(0) }}
              className="w-full text-sm border border-neutral-300 dark:border-neutral-600 rounded-md px-2 py-1.5 bg-white dark:bg-neutral-700 text-neutral-800 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-primary-500">
              <option value="">All types</option>
              {EVENT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-neutral-500 mb-1">Outcome</label>
            <select value={outcome} onChange={e => { setOutcome(e.target.value); setOffset(0) }}
              className="w-full text-sm border border-neutral-300 dark:border-neutral-600 rounded-md px-2 py-1.5 bg-white dark:bg-neutral-700 text-neutral-800 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-primary-500">
              <option value="">All outcomes</option>
              {OUTCOMES.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-neutral-500 mb-1">From</label>
            <input type="datetime-local" value={startDate} onChange={e => { setStartDate(e.target.value); setOffset(0) }}
              className="w-full text-sm border border-neutral-300 dark:border-neutral-600 rounded-md px-2 py-1.5 bg-white dark:bg-neutral-700 text-neutral-800 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-primary-500" />
          </div>
          <div>
            <label className="block text-xs font-medium text-neutral-500 mb-1">To</label>
            <input type="datetime-local" value={endDate} onChange={e => { setEndDate(e.target.value); setOffset(0) }}
              className="w-full text-sm border border-neutral-300 dark:border-neutral-600 rounded-md px-2 py-1.5 bg-white dark:bg-neutral-700 text-neutral-800 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-primary-500" />
          </div>
          <div>
            <label className="block text-xs font-medium text-neutral-500 mb-1">IP Address</label>
            <input type="text" value={ipFilter} onChange={e => { setIpFilter(e.target.value); setOffset(0) }}
              placeholder="e.g. 192.168."
              className="w-full text-sm border border-neutral-300 dark:border-neutral-600 rounded-md px-2 py-1.5 bg-white dark:bg-neutral-700 text-neutral-800 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono" />
          </div>
        </div>
      </div>
      <div className="bg-white dark:bg-neutral-800 rounded-lg shadow-sm border border-neutral-200 dark:border-neutral-700 overflow-hidden">
        <div className="overflow-x-auto">
          {loading ? (
            <div className="flex justify-center py-12">
              <div className="animate-spin h-6 w-6 border-2 border-primary-600 border-t-transparent rounded-full" />
            </div>
          ) : entries.length === 0 ? (
            <div className="text-center py-12 text-neutral-400">No audit events match your filters</div>
          ) : (
            <table className="w-full text-sm" aria-label="Audit log entries">
              <thead>
                <tr className="bg-neutral-50 dark:bg-neutral-700 text-left">
                  <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase">#</th>
                  <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase">Timestamp</th>
                  <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase">Type</th>
                  <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase">Action</th>
                  <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase">Outcome</th>
                  <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase">Resource</th>
                  <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase">IP Address</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-200 dark:divide-neutral-700">
                {entries.map(e => (
                  <tr key={e.id}
                    onClick={() => setSelectedEntry(selectedEntry?.id === e.id ? null : e)}
                    className="hover:bg-neutral-50 dark:hover:bg-neutral-700/50 cursor-pointer transition-colors">
                    <td className="px-4 py-3 text-xs text-neutral-400 font-mono">{e.sequence_num}</td>
                    <td className="px-4 py-3 text-xs text-neutral-500">
                      {formatIST(e.timestamp)}
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-xs font-mono text-primary-600 dark:text-primary-400">{e.event_type}</span>
                    </td>
                    <td className="px-4 py-3 text-xs text-neutral-700 dark:text-neutral-300 font-mono">{e.action}</td>
                    <td className="px-4 py-3"><OutcomeBadge outcome={e.outcome} /></td>
                    <td className="px-4 py-3 text-xs text-neutral-500">
                      {e.resource_type ? `${e.resource_type}` : '—'}
                    </td>
                    <td className="px-4 py-3 text-xs font-mono text-neutral-600 dark:text-neutral-400">
                      {e.ip_address || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Detail panel */}
        {selectedEntry && (
          <div className="border-t border-neutral-200 dark:border-neutral-700 p-4 bg-neutral-50 dark:bg-neutral-900">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-neutral-700 dark:text-neutral-300">Entry #{selectedEntry.sequence_num} detail</h3>
              <button onClick={() => setSelectedEntry(null)} className="text-xs text-neutral-400 hover:text-neutral-600">✕ Close</button>
            </div>
            <pre className="text-xs bg-neutral-100 dark:bg-neutral-800 rounded p-3 overflow-x-auto">
              {JSON.stringify(selectedEntry, null, 2)}
            </pre>
          </div>
        )}

        {/* Pagination */}
        {total > PAGE_SIZE && (
          <div className="px-4 py-3 border-t border-neutral-200 dark:border-neutral-700 flex items-center justify-between text-sm">
            <span className="text-neutral-500">
              Showing {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total.toLocaleString()}
            </span>
            <div className="flex gap-2">
              <button onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} disabled={page === 1}
                className="px-3 py-1 border border-neutral-300 rounded disabled:opacity-40 hover:bg-neutral-50 text-neutral-600">
                ← Prev
              </button>
              <span className="px-3 py-1 text-neutral-500">Page {page} / {totalPages}</span>
              <button onClick={() => setOffset(offset + PAGE_SIZE)} disabled={page >= totalPages}
                className="px-3 py-1 border border-neutral-300 rounded disabled:opacity-40 hover:bg-neutral-50 text-neutral-600">
                Next →
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
