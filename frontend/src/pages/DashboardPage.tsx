import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { systemApi, SystemStatus } from '../api/system'
import { formatIST, formatISTDate } from '../utils/dates'
import { settingsApi, DashboardSummary, activityApi, ActivityItem } from '../api/settings'
import { useAuthStore } from '../stores/authStore'

// ------------------------------------------------------------------
// Metric card
// ------------------------------------------------------------------
function MetricCard({ label, value, sub, icon }: {
  label: string; value: string | number; sub?: string; icon: string
}) {
  return (
    <div className="bg-white dark:bg-neutral-800 rounded-lg shadow-sm border border-neutral-200 dark:border-neutral-700 p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">{label}</p>
          <p className="text-2xl font-bold text-neutral-900 dark:text-neutral-100 mt-1">{value}</p>
          {sub && <p className="text-xs text-neutral-400 mt-0.5">{sub}</p>}
        </div>
        <span className="text-2xl" aria-hidden="true">{icon}</span>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------
// Service row
// ------------------------------------------------------------------
function ServiceRow({ name, svc }: { name: string; svc: { status: string; latency_ms?: number } }) {
  const up = svc.status === 'up'
  return (
    <div className="flex items-center justify-between py-2 border-b border-neutral-100 dark:border-neutral-700 last:border-0">
      <span className="text-sm text-neutral-700 dark:text-neutral-300 capitalize">{name}</span>
      <div className="flex items-center gap-2">
        {svc.latency_ms != null && (
          <span className="text-xs text-neutral-400">{svc.latency_ms}ms</span>
        )}
        <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium
          ${up ? 'bg-success-100 text-success-700' : 'bg-danger-100 text-danger-700'}`}>
          ● {up ? 'Online' : 'Offline'}
        </span>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------
// Activity item
// ------------------------------------------------------------------
const EVENT_ICONS: Record<string, string> = {
  auth: '🔑', model: '🤖', document: '📄', rag: '🧠',
  agent: '⚙️', tool: '🔧', sandbox: '🐳', approval: '✅',
  config: '⚙️', error: '❌', security: '🛡️',
}
const OUTCOME_STYLE: Record<string, string> = {
  success: 'text-success-700', failure: 'text-danger-600', pending: 'text-warning-600',
}

function ActivityRow({ item }: { item: ActivityItem }) {
  const icon = EVENT_ICONS[item.event_type] || '📋'
  const timeAgo = (() => {
    const diff = Date.now() - new Date(item.timestamp).getTime()
    if (diff < 60000) return `${Math.round(diff / 1000)}s ago`
    if (diff < 3600000) return `${Math.round(diff / 60000)}m ago`
    if (diff < 86400000) return `${Math.round(diff / 3600000)}h ago`
    return formatISTDate(item.timestamp)
  })()

  return (
    <div className="flex items-start gap-3 py-2.5 border-b border-neutral-100 dark:border-neutral-700 last:border-0">
      <span className="text-base flex-shrink-0 mt-0.5" aria-hidden="true">{icon}</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-neutral-800 dark:text-neutral-100 truncate">{item.action}</p>
        <p className="text-xs text-neutral-400 mt-0.5">
          <span className={OUTCOME_STYLE[item.outcome] || 'text-neutral-500'}>{item.outcome}</span>
          {item.resource_type && <span> · {item.resource_type}</span>}
        </p>
      </div>
      <span className="text-xs text-neutral-400 flex-shrink-0 mt-0.5">{timeAgo}</span>
    </div>
  )
}

// ------------------------------------------------------------------
// Dashboard page
// ------------------------------------------------------------------
export default function DashboardPage() {
  const { user } = useAuthStore()
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [activity, setActivity] = useState<ActivityItem[]>([])
  const [loading, setLoading] = useState(true)

  const load = async () => {
    const [s, sum, act] = await Promise.allSettled([
      systemApi.status(),
      settingsApi.summary(),
      activityApi.recent(10),
    ])
    if (s.status === 'fulfilled') setStatus(s.value)
    if (sum.status === 'fulfilled') setSummary(sum.value)
    if (act.status === 'fulfilled') setActivity(act.value.items)
    setLoading(false)
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 30_000)
    return () => clearInterval(id)
  }, [])

  const r = status?.resources

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">Dashboard</h1>
        <p className="text-sm text-neutral-500 mt-1">
          Welcome back, <strong>{user?.username}</strong>
          <span className="ml-2 text-xs text-neutral-400">(Role: {user?.role})</span>
        </p>
      </div>

      {/* Privacy banner */}
      <div className="mb-6 flex items-center gap-2 text-xs text-success-700 bg-success-50 border border-success-200 rounded-lg px-3 py-2 w-fit">
        <span aria-hidden="true">🔒</span>
        All AI processing is running locally on this device — no data leaves your network
      </div>

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="bg-neutral-100 dark:bg-neutral-800 rounded-lg h-24 animate-pulse" />
          ))}
        </div>
      ) : (
        <>
          {/* Metric cards — row 1: resources */}
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-4">
            <MetricCard label="CPU Usage" value={`${r?.cpu_percent ?? '—'}%`} icon="💻" />
            <MetricCard
              label="RAM Usage"
              value={`${r?.ram_used_gb ?? '—'} GB`}
              sub={r ? `of ${r.ram_total_gb} GB total` : undefined}
              icon="🧠"
            />
            <MetricCard
              label="Disk Free"
              value={r ? `${(r.disk_total_gb - r.disk_used_gb).toFixed(1)} GB` : '—'}
              sub={r ? `${r.disk_total_gb} GB total` : undefined}
              icon="💾"
            />
            <MetricCard
              label="Models Loaded"
              value={status?.models_loaded?.length ?? '—'}
              sub={status?.models_loaded?.[0] ?? 'None'}
              icon="🤖"
            />
          </div>

          {/* Metric cards — row 2: application counts */}
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
            <MetricCard label="Knowledge Bases" value={summary?.knowledge_base_count ?? '—'} icon="🧠" />
            <MetricCard label="Documents" value={summary?.document_count ?? '—'} icon="📄" />
            <MetricCard label="Agent Runs" value={summary?.agent_run_count ?? '—'} icon="⚙️" />
            <MetricCard
              label="Pending Approvals"
              value={summary?.pending_approval_count ?? '—'}
              sub={summary?.pending_approval_count ? 'action required' : 'none pending'}
              icon="✅"
            />
          </div>

          {/* Three-panel row */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

            {/* Activity feed */}
            <div className="lg:col-span-2 bg-white dark:bg-neutral-800 rounded-lg shadow-sm border border-neutral-200 dark:border-neutral-700 p-5">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-base font-semibold text-neutral-800 dark:text-neutral-100">Recent Activity</h2>
                {user?.role === 'admin' && (
                  <Link to="/audit" className="text-xs text-primary-600 hover:underline">View all →</Link>
                )}
              </div>
              {activity.length === 0 ? (
                <p className="text-sm text-neutral-400 py-4 text-center">No activity yet</p>
              ) : (
                activity.map(item => <ActivityRow key={item.id} item={item} />)
              )}
            </div>

            {/* Right column */}
            <div className="space-y-4">

              {/* Services */}
              <div className="bg-white dark:bg-neutral-800 rounded-lg shadow-sm border border-neutral-200 dark:border-neutral-700 p-5">
                <h2 className="text-base font-semibold text-neutral-800 dark:text-neutral-100 mb-3">Services</h2>
                {status?.services
                  ? Object.entries(status.services).map(([name, svc]) => (
                      <ServiceRow key={name} name={name} svc={svc} />
                    ))
                  : <p className="text-sm text-neutral-400">Unavailable</p>}
              </div>

              {/* Quick actions */}
              <div className="bg-white dark:bg-neutral-800 rounded-lg shadow-sm border border-neutral-200 dark:border-neutral-700 p-5">
                <h2 className="text-base font-semibold text-neutral-800 dark:text-neutral-100 mb-3">Quick Actions</h2>
                <div className="flex flex-col gap-2">
                  <Link to="/chat"
                    className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700 transition-colors">
                    💬 New Chat
                  </Link>
                  <Link to="/knowledge-bases"
                    className="flex items-center gap-2 px-4 py-2 bg-white dark:bg-neutral-700 text-neutral-700 dark:text-neutral-200 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm font-medium hover:bg-neutral-50 transition-colors">
                    🧠 Knowledge Bases
                  </Link>
                  <Link to="/agents"
                    className="flex items-center gap-2 px-4 py-2 bg-white dark:bg-neutral-700 text-neutral-700 dark:text-neutral-200 border border-neutral-300 dark:border-neutral-600 rounded-md text-sm font-medium hover:bg-neutral-50 transition-colors">
                    🤖 New Agent Run
                  </Link>
                  {user?.role === 'admin' && summary?.pending_approval_count ? (
                    <Link to="/approvals"
                      className="flex items-center gap-2 px-4 py-2 bg-warning-50 text-warning-700 border border-warning-200 rounded-md text-sm font-medium hover:bg-warning-100 transition-colors">
                      ⚠️ {summary.pending_approval_count} Pending Approval{summary.pending_approval_count > 1 ? 's' : ''}
                    </Link>
                  ) : null}
                </div>
              </div>

            </div>
          </div>
        </>
      )}
    </div>
  )
}
