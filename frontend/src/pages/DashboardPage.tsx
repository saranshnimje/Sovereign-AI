import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { systemApi, SystemStatus, ResourceMetrics } from '../api/system'
import { formatISTDate } from '../utils/dates'
import { settingsApi, DashboardSummary, activityApi, ActivityItem } from '../api/settings'
import { useAuthStore } from '../stores/authStore'

function timeAgo(ts: string) {
  const diff = Date.now() - new Date(ts).getTime()
  if (diff < 60000) return `${Math.round(diff / 1000)}s ago`
  if (diff < 3600000) return `${Math.round(diff / 60000)}m ago`
  if (diff < 86400000) return `${Math.round(diff / 3600000)}h ago`
  return formatISTDate(ts)
}

const ACTIVITY_COLORS: Record<string, string> = {
  success: 'bg-green-500', failure: 'bg-red-500', pending: 'bg-yellow-500',
}

/* ── donut chart ──────────────────────────────────────────────── */
function DonutChart({ segments, center }: {
  segments: { label: string; value: number; color: string }[]
  center: { label: string; value: string }
}) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1
  let cumulative = 0
  const r = 40, c = 2 * Math.PI * r
  return (
    <div className="relative flex items-center justify-center">
      <svg viewBox="0 0 100 100" className="w-28 h-28 -rotate-90">
        {segments.map((seg, i) => {
          const pct = seg.value / total
          const off = c * cumulative
          const len = c * pct
          cumulative += pct
          return <circle key={i} cx="50" cy="50" r={r} fill="none" stroke={seg.color} strokeWidth="7" strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-off} />
        })}
      </svg>
      <div className="absolute text-center">
        <p className="text-lg font-bold text-white">{center.value}</p>
        <p className="text-[9px] text-neutral-500">{center.label}</p>
      </div>
    </div>
  )
}

/* ── circle progress ──────────────────────────────────────────── */
function CircleProgress({ value, label }: { value: number; label: string }) {
  const r = 42, c = 2 * Math.PI * r
  const off = c * (1 - value / 100)
  return (
    <div className="relative flex items-center justify-center">
      <svg viewBox="0 0 100 100" className="w-32 h-32 -rotate-90">
        <circle cx="50" cy="50" r={r} fill="none" stroke="#0d260d" strokeWidth="5" />
        <circle cx="50" cy="50" r={r} fill="none" stroke="#22c55e" strokeWidth="5" strokeDasharray={c} strokeDashoffset={off} strokeLinecap="round" className="transition-all duration-700" />
      </svg>
      <div className="absolute text-center">
        <p className="text-xl font-bold text-white">{value}%</p>
        <p className="text-[9px] text-neutral-500">{label}</p>
      </div>
    </div>
  )
}

/* ── mini bar chart ───────────────────────────────────────────── */
function MiniBarChart({ data, color = '#22c55e' }: { data: number[]; color?: string }) {
  const max = Math.max(...data, 1)
  return (
    <div className="flex items-end gap-[3px] h-10">
      {data.map((v, i) => (
        <div key={i} className="flex-1 rounded-t transition-all" style={{ height: `${(v / max) * 100}%`, background: `${color}33` }} />
      ))}
    </div>
  )
}

/* ── live line chart (SVG) ────────────────────────────────────── */
function LiveLineChart({ lines, maxPoints = 30 }: {
  lines: { data: number[]; color: string; label: string }[]
  maxPoints?: number
}) {
  const w = 500, h = 140, padL = 35, padR = 10, padT = 10, padB = 20
  const chartW = w - padL - padR
  const chartH = h - padT - padB

  const allVals = lines.flatMap(l => l.data)
  const max = Math.max(...allVals, 1)
  const min = 0
  const range = max - min || 1

  const toPath = (data: number[]) => {
    if (data.length < 2) return ''
    const xStep = chartW / (maxPoints - 1)
    return data.map((v, i) => {
      const x = padL + i * xStep
      const y = padT + chartH - ((v - min) / range) * chartH
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    }).join(' ')
  }

  // Y-axis labels
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map(pct => ({
    pct,
    value: Math.round(min + pct * range),
    y: padT + chartH - pct * chartH,
  }))

  return (
    <div className="w-full">
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full" style={{ height: '160px' }}>
        {/* Grid lines */}
        {yTicks.map((tick) => (
          <g key={tick.pct}>
            <line x1={padL} y1={tick.y} x2={w - padR} y2={tick.y} stroke="#0d260d" strokeWidth="1" />
            <text x={padL - 5} y={tick.y + 3} textAnchor="end" fill="#525252" fontSize="8">{tick.value}%</text>
          </g>
        ))}
        {/* Lines */}
        {lines.map((line, i) => (
          <path key={i} d={toPath(line.data)} fill="none" stroke={line.color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        ))}
        {/* Legend */}
        {lines.map((line, i) => (
          <g key={`leg-${i}`}>
            <rect x={padL + i * 70} y={h - 6} width={8} height={3} rx={1} fill={line.color} />
            <text x={padL + i * 70 + 11} y={h - 3} fill="#737373" fontSize="7">{line.label}</text>
          </g>
        ))}
      </svg>
    </div>
  )
}

/* ── page ─────────────────────────────────────────────────────── */
export default function DashboardPage() {
  const { user } = useAuthStore()
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [activity, setActivity] = useState<ActivityItem[]>([])
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date())

  // Current resource values (refreshed on each poll)
  const [cpuCurrent, setCpuCurrent] = useState(0)
  const [ramCurrent, setRamCurrent] = useState(0)
  const [diskCurrent, setDiskCurrent] = useState(0)

  // Track previous values for flash animation
  const prevRef = useRef({ cpu: 0, ram: 0, disk: 0, agentRuns: 0, docCount: 0, kbCount: 0 })
  const [flash, setFlash] = useState<Record<string, boolean>>({})

  const triggerFlash = (key: string) => {
    setFlash(prev => ({ ...prev, [key]: true }))
    setTimeout(() => setFlash(prev => ({ ...prev, [key]: false })), 600)
  }

  const load = async () => {
    const [s, sum, act] = await Promise.allSettled([
      systemApi.status(), settingsApi.summary(), activityApi.recent(10),
    ])
    if (s.status === 'fulfilled') {
      setStatus(s.value)
      const r = s.value.resources
      const prev = prevRef.current
      if (prev.cpu !== r.cpu_percent) triggerFlash('cpu')
      if (prev.ram !== Math.round((r.ram_used_gb / r.ram_total_gb) * 100)) triggerFlash('ram')
      if (prev.disk !== Math.round((r.disk_used_gb / r.disk_total_gb) * 100)) triggerFlash('disk')
      prev.cpu = r.cpu_percent
      prev.ram = Math.round((r.ram_used_gb / r.ram_total_gb) * 100)
      prev.disk = Math.round((r.disk_used_gb / r.disk_total_gb) * 100)
      setCpuCurrent(r.cpu_percent)
      setRamCurrent(prev.ram)
      setDiskCurrent(prev.disk)
    }
    if (sum.status === 'fulfilled') {
      const prev = prevRef.current
      if (prev.agentRuns !== sum.value.agent_run_count) triggerFlash('agentRuns')
      if (prev.docCount !== sum.value.document_count) triggerFlash('docCount')
      if (prev.kbCount !== sum.value.knowledge_base_count) triggerFlash('kbCount')
      prev.agentRuns = sum.value.agent_run_count
      prev.docCount = sum.value.document_count
      prev.kbCount = sum.value.knowledge_base_count
      setSummary(sum.value)
    }
    if (act.status === 'fulfilled') setActivity(act.value.items)
    setLastUpdate(new Date())
    setLoading(false)
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 1000) // Poll every 1s
    return () => clearInterval(id)
  }, [])

  const r = status?.resources
  const kbCount = summary?.knowledge_base_count ?? 0
  const docCount = summary?.document_count ?? 0
  const agentRuns = summary?.agent_run_count ?? 0
  const pendingApprovals = summary?.pending_approval_count ?? 0

  const servicesUp = status?.services ? Object.values(status.services).filter(s => s.status === 'up').length : 0
  const servicesTotal = status?.services ? Object.values(status.services).length : 1
  const servicesPct = Math.round((servicesUp / servicesTotal) * 100)

  return (
    <div className="min-h-full space-y-5">
      {/* ── Header row ─────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            Welcome back, {user?.username} <span className="text-2xl">👋</span>
          </h1>
          <p className="text-sm text-neutral-500 mt-0.5">Monitor. Orchestrate. Optimize. AI operations, redefined.</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 px-3 py-1.5 bg-green-950/30 border border-green-900/20 rounded-lg">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
            </span>
            <span className="text-[10px] text-green-400 font-medium">LIVE</span>
            <span className="text-[10px] text-neutral-500">· {lastUpdate.toLocaleTimeString()}</span>
          </div>
          <Link to="/chat" className="px-4 py-2 bg-green-600 hover:bg-green-500 text-white rounded-lg text-sm font-medium transition-colors shadow-lg shadow-green-900/30">
            + New Chat
          </Link>
        </div>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => <div key={i} className="bg-[#0a1a0a] border border-green-900/30 rounded-xl h-28 animate-pulse" />)}
        </div>
      ) : (
        <>
          {/* ── Stat cards ──────────────────────────────────────── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
            {[
              { label: 'Chat Sessions', value: agentRuns, icon: '💬', sub: 'Total conversations', key: 'agentRuns' },
              { label: 'Documents', value: docCount, icon: '📄', sub: 'Indexed in knowledge bases', key: 'docCount' },
              { label: 'Knowledge Bases', value: kbCount, icon: '🧠', sub: 'Active collections', key: 'kbCount' },
              { label: 'Models Loaded', value: status?.models_loaded?.length ?? 0, icon: '🤖', sub: status?.models_loaded?.[0] || 'None loaded', key: 'models' },
            ].map((card, i) => (
              <div key={i} className="bg-[#0a1a0a] border border-green-900/40 rounded-xl p-5 relative overflow-hidden group hover:border-green-700/50 transition-all">
                <div className="absolute inset-0 bg-gradient-to-br from-green-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
                <div className="relative flex items-start justify-between">
                  <div>
                    <p className="text-xs font-medium text-green-500/70 uppercase tracking-wider">{card.label}</p>
                    <p className={`text-2xl font-bold text-white mt-1 transition-all duration-300 ${flash[card.key] ? 'scale-110 text-green-400' : ''}`}>
                      {card.value}
                    </p>
                    <p className="text-[10px] text-neutral-500 mt-0.5">{card.sub}</p>
                  </div>
                  <div className={`w-10 h-10 rounded-lg bg-green-500/10 flex items-center justify-center text-lg transition-all duration-300 ${flash[card.key] ? 'bg-green-500/25 scale-110' : ''}`}>
                    {card.icon}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* ── Main grid: Chart + Activity ────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            {/* System Overview — Live bars */}
            <div className="lg:col-span-2 bg-[#0a1a0a] border border-green-900/40 rounded-xl p-5">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-base font-semibold text-white">System Overview</h2>
                <span className="text-[10px] text-green-400">Updated {lastUpdate.toLocaleTimeString()}</span>
              </div>
              {[
                { label: 'CPU', value: cpuCurrent, color: '#4ade80', glow: 'shadow-green-500/30', detail: `${cpuCurrent}% used`, key: 'cpu' },
                { label: 'RAM', value: ramCurrent, color: '#60a5fa', glow: 'shadow-blue-500/30', detail: r ? `${r.ram_used_gb} / ${r.ram_total_gb} GB` : '—', key: 'ram' },
                { label: 'Disk', value: diskCurrent, color: '#facc15', glow: 'shadow-yellow-500/30', detail: r ? `${r.disk_used_gb} / ${r.disk_total_gb} GB` : '—', key: 'disk' },
              ].map((bar) => (
                <div key={bar.label} className={`mb-4 last:mb-0 p-3 rounded-lg bg-[#050e05] border border-green-900/20 transition-all duration-300 ${flash[bar.key] ? `shadow-lg ${bar.glow}` : ''}`}>
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full" style={{ background: bar.color }} />
                      <span className="text-xs font-medium text-neutral-300">{bar.label}</span>
                    </div>
                    <div className="text-right">
                      <span className={`text-sm font-bold text-white ${flash[bar.key] ? 'scale-110 inline-block' : ''}`}>{bar.value}%</span>
                      <span className="text-[10px] text-neutral-500 ml-2">{bar.detail}</span>
                    </div>
                  </div>
                  <div className="h-3 bg-green-950/40 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-300"
                      style={{
                        width: `${bar.value}%`,
                        background: `linear-gradient(90deg, ${bar.color}88, ${bar.color})`,
                        boxShadow: flash[bar.key] ? `0 0 12px ${bar.color}66` : 'none',
                      }}
                    />
                  </div>
                  <div className="flex justify-between mt-1 text-[8px] text-neutral-600">
                    <span>0%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span>
                  </div>
                </div>
              ))}
            </div>

            {/* Live Activity */}
            <div className="bg-[#0a1a0a] border border-green-900/40 rounded-xl p-5">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-base font-semibold text-white">Live Activity</h2>
                {user?.role === 'admin' && <Link to="/audit" className="text-[10px] text-green-400 hover:text-green-300">View all →</Link>}
              </div>
              {activity.length === 0 ? (
                <p className="text-sm text-neutral-500 py-4 text-center">No activity yet</p>
              ) : (
                <div className="space-y-0 max-h-72 overflow-y-auto pr-1">
                  {activity.map(item => (
                    <div key={item.id} className="flex items-start gap-3 py-2.5 border-b border-green-900/15 last:border-0">
                      <div className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${ACTIVITY_COLORS[item.outcome] || 'bg-neutral-500'}`} />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs text-neutral-200 truncate">{item.action}</p>
                        <p className="text-[10px] text-neutral-500 mt-0.5">{item.resource_type || item.event_type}</p>
                      </div>
                      <span className="text-[10px] text-neutral-600 flex-shrink-0">{timeAgo(item.timestamp)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* ── Bottom row ──────────────────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            {/* System Health */}
            <div className="bg-[#0a1a0a] border border-green-900/40 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-white mb-3">System Health</h2>
              <div className="flex items-center justify-center py-1">
                <CircleProgress value={servicesPct} label="Services Up" />
              </div>
              <div className="mt-3 space-y-1.5">
                {status?.services && Object.entries(status.services).map(([name, svc]) => (
                  <div key={name} className="flex items-center justify-between py-1.5 border-b border-green-900/15 last:border-0">
                    <span className="text-xs text-neutral-400 capitalize">{name}</span>
                    <div className="flex items-center gap-2">
                      {svc.latency_ms != null && <span className="text-[10px] text-neutral-600">{svc.latency_ms}ms</span>}
                      <span className={`text-[10px] ${svc.status === 'up' ? 'text-green-400' : 'text-red-400'}`}>
                        ● {svc.status === 'up' ? 'Operational' : 'Offline'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Quick Actions + Uptime */}
            <div className="space-y-4">
              <div className="bg-[#0a1a0a] border border-green-900/40 rounded-xl p-5">
                <h2 className="text-sm font-semibold text-white mb-3">Quick Actions</h2>
                <div className="flex flex-col gap-2">
                  <Link to="/chat" className="flex items-center gap-2 px-4 py-2.5 bg-green-600/20 border border-green-600/40 text-green-400 rounded-lg text-sm font-medium hover:bg-green-600/30 transition-colors">
                    💬 New Chat
                  </Link>
                  <Link to="/models" className="flex items-center gap-2 px-4 py-2.5 bg-[#050e05] border border-green-900/30 text-neutral-300 rounded-lg text-sm font-medium hover:bg-green-900/15 transition-colors">
                    🧩 Browse Models
                  </Link>
                  <Link to="/providers" className="flex items-center gap-2 px-4 py-2.5 bg-[#050e05] border border-green-900/30 text-neutral-300 rounded-lg text-sm font-medium hover:bg-green-900/15 transition-colors">
                    ⚡ LLM Providers
                  </Link>
                </div>
              </div>
              <div className="bg-[#0a1a0a] border border-green-900/40 rounded-xl p-5">
                <p className="text-[10px] text-neutral-500 uppercase tracking-wider mb-1">System Uptime</p>
                <p className="text-xl font-bold text-green-400">{servicesPct}%</p>
                <MiniBarChart data={[cpuCurrent, ramCurrent, diskCurrent]} />
                <p className="text-[10px] text-neutral-600 mt-1">Current usage</p>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
