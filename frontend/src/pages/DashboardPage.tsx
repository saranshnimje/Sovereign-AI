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

const ACTIVITY_ICONS: Record<string, { icon: string; color: string }> = {
  success: { icon: '✓', color: 'text-success-500 bg-success-500/10' },
  failure: { icon: '✗', color: 'text-danger-500 bg-danger-500/10' },
  pending: { icon: '◷', color: 'text-warning-500 bg-warning-500/10' },
}

function SovereigntyScore({ score }: { score: number }) {
  const r = 58, c = 2 * Math.PI * r
  const off = c * (1 - score / 100)
  return (
    <div className="relative flex items-center justify-center">
      <svg viewBox="0 0 140 140" className="w-24 h-24 md:w-36 md:h-36 -rotate-90">
        <circle cx="70" cy="70" r={r} fill="none" stroke="#1e2d4a" strokeWidth="6" />
        <circle cx="70" cy="70" r={r} fill="none" stroke="#06b6d4" strokeWidth="6" strokeDasharray={c} strokeDashoffset={off} strokeLinecap="round" className="transition-all duration-700" />
      </svg>
      <div className="absolute text-center">
        <p className="text-2xl md:text-3xl font-bold text-white">{score}</p>
        <p className="text-[9px] text-cyan-400 uppercase tracking-wider">Sovereignty Score</p>
      </div>
    </div>
  )
}

function LiveLineChart({ lines, maxPoints = 30 }: {
  lines: { data: number[]; color: string; label: string }[]
  maxPoints?: number
}) {
  const w = 500, h = 120, padL = 35, padR = 10, padT = 10, padB = 20
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
  const yTicks = [0, 0.5, 1].map(pct => ({ pct, value: Math.round(min + pct * range), y: padT + chartH - pct * chartH }))
  return (
    <div className="w-full">
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full" style={{ height: '140px' }}>
        {yTicks.map((tick) => <g key={tick.pct}><line x1={padL} y1={tick.y} x2={w - padR} y2={tick.y} stroke="#1e2d4a" strokeWidth="1" /><text x={padL - 5} y={tick.y + 3} textAnchor="end" fill="#6b7280" fontSize="8">{tick.value}%</text></g>)}
        {lines.map((line, i) => <path key={i} d={toPath(line.data)} fill="none" stroke={line.color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />)}
        {lines.map((line, i) => <g key={`leg-${i}`}><rect x={padL + i * 70} y={h - 6} width={8} height={3} rx={1} fill={line.color} /><text x={padL + i * 70 + 11} y={h - 3} fill="#9ca3af" fontSize="7">{line.label}</text></g>)}
      </svg>
    </div>
  )
}

export default function DashboardPage() {
  const { user } = useAuthStore()
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [activity, setActivity] = useState<ActivityItem[]>([])
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date())
  const [cpuCurrent, setCpuCurrent] = useState(0)
  const [ramCurrent, setRamCurrent] = useState(0)
  const prevRef = useRef({ cpu: 0, ram: 0, agentRuns: 0, docCount: 0, kbCount: 0 })
  const [flash, setFlash] = useState<Record<string, boolean>>({})
  const loadingRef = useRef(false)

  const triggerFlash = (key: string) => {
    setFlash(prev => ({ ...prev, [key]: true }))
    setTimeout(() => setFlash(prev => ({ ...prev, [key]: false })), 600)
  }

  const load = async () => {
    // Never allow a polling tick to overlap the previous request batch.
    if (loadingRef.current) return
    loadingRef.current = true
    try {
      const [s, sum, act] = await Promise.allSettled([
        systemApi.status(), settingsApi.summary(), activityApi.recent(8),
      ])
      if (s.status === 'fulfilled') {
        setStatus(s.value)
        const r = s.value.resources
        const prev = prevRef.current
        if (prev.cpu !== r.cpu_percent) triggerFlash('cpu')
        const ramPercent = r.ram_total_gb > 0 ? Math.round((r.ram_used_gb / r.ram_total_gb) * 100) : 0
        if (prev.ram !== ramPercent) triggerFlash('ram')
        prev.cpu = r.cpu_percent
        prev.ram = ramPercent
        setCpuCurrent(r.cpu_percent)
        setRamCurrent(ramPercent)
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
    } finally {
      loadingRef.current = false
    }
  }

  useEffect(() => {
    void load()
    const id = setInterval(() => void load(), 10_000)
    return () => clearInterval(id)
  }, [])

  const r = status?.resources
  const kbCount = summary?.knowledge_base_count ?? 0
  const docCount = summary?.document_count ?? 0
  const agentRuns = summary?.agent_run_count ?? 0
  const pendingApprovals = summary?.pending_approval_count ?? 0
  const modelsLoaded = status?.models_loaded?.length ?? 0
  const servicesUp = status?.services ? Object.values(status.services).filter(s => s.status === 'up').length : 0
  const servicesTotal = status?.services ? Object.values(status.services).length : 1
  const sovereigntyScore = Math.round((servicesUp / servicesTotal) * 100)

  return (
    <div className="min-h-full space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div><h1 className="text-lg md:text-xl font-bold text-white">Dashboard</h1><p className="text-xs text-neutral-400 mt-0.5">Monitor. Orchestrate. Optimize.</p></div>
        <div className="flex items-center gap-3"><div className="flex items-center gap-1.5 px-3 py-1.5 bg-surface-raised border border-surface-border rounded-lg"><span className={`w-2 h-2 rounded-full ${status?.status === 'healthy' ? 'bg-success-500' : 'bg-danger-500'}`} /><span className="text-[10px] text-neutral-400">Updated {lastUpdate.toLocaleTimeString()}</span></div></div>
      </div>
      {loading ? <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">{[...Array(4)].map((_, i) => <div key={i} className="skeleton h-28" />)}</div> : (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            <div className="bg-surface-raised border border-surface-border rounded-xl p-6 flex flex-col items-center justify-center"><SovereigntyScore score={sovereigntyScore} /><p className="text-sm font-medium text-success-500 mt-3">FULLY LOCAL</p><p className="text-[10px] text-neutral-500 mt-1">{servicesUp}/{servicesTotal} services operational</p></div>
            <div className="bg-surface-raised border border-surface-border rounded-xl p-5"><h2 className="text-sm font-semibold text-white mb-4">System Health</h2><div className="space-y-3">{status?.services && Object.entries(status.services).map(([name, svc]) => <div key={name} className="flex items-center justify-between p-2.5 bg-surface-overlay rounded-lg border border-surface-border"><div className="flex items-center gap-2.5"><span className={`w-2.5 h-2.5 rounded-full ${svc.status === 'up' ? 'bg-success-500' : 'bg-danger-500'}`} /><span className="text-sm text-neutral-200">{name === 'llm' ? 'LLM' : name.charAt(0).toUpperCase() + name.slice(1)}</span></div><div className="flex items-center gap-2">{svc.latency_ms != null && <span className="text-[10px] text-neutral-500">{svc.latency_ms}ms</span>}<span className={`text-[10px] font-medium ${svc.status === 'up' ? 'text-success-500' : 'text-danger-500'}`}>{svc.status === 'up' ? 'Online' : 'Offline'}</span></div></div>)}</div></div>
            <div className="bg-surface-raised border border-surface-border rounded-xl p-5"><h2 className="text-sm font-semibold text-white mb-4">Resources</h2><div className="space-y-4"><div><div className="flex items-center justify-between mb-1.5"><span className="text-xs text-neutral-400">CPU</span><span className={`text-sm font-bold text-white ${flash['cpu'] ? 'text-cyan-400' : ''}`}>{cpuCurrent}%</span></div><div className="h-2 bg-surface-overlay rounded-full overflow-hidden"><div className="h-full rounded-full bg-cyan-500 transition-all duration-300" style={{ width: `${cpuCurrent}%` }} /></div></div><div><div className="flex items-center justify-between mb-1.5"><span className="text-xs text-neutral-400">RAM</span><span className={`text-sm font-bold text-white ${flash['ram'] ? 'text-cyan-400' : ''}`}>{r ? `${r.ram_used_gb} / ${r.ram_total_gb} GB` : '—'}</span></div><div className="h-2 bg-surface-overlay rounded-full overflow-hidden"><div className="h-full rounded-full bg-navy-400 transition-all duration-300" style={{ width: `${ramCurrent}%` }} /></div></div><div className="pt-2 border-t border-surface-border"><p className="text-xs text-neutral-400 mb-2">Models Loaded</p>{status?.models_loaded && status.models_loaded.length > 0 ? <div className="space-y-1.5">{status.models_loaded.map((m, i) => <div key={i} className="flex items-center gap-2 px-2 py-1 bg-surface-overlay rounded-md"><span className="w-1.5 h-1.5 rounded-full bg-success-500 animate-pulse-cyan" /><span className="text-[11px] text-neutral-300 truncate">{m}</span><span className="ml-auto text-[9px] text-success-500 font-medium">Ready</span></div>)}</div> : <p className="text-[11px] text-neutral-500">No models loaded</p>}</div></div></div>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">{[{ label: 'Agent Runs', value: agentRuns, icon: 'Agents', color: 'text-cyan-400', key: 'agentRuns' }, { label: 'Knowledge Bases', value: kbCount, icon: 'KB', color: 'text-navy-400', key: 'kbCount' }, { label: 'Documents', value: docCount, icon: 'Docs', color: 'text-cyan-300', key: 'docCount' }, { label: 'Pending Approvals', value: pendingApprovals, icon: 'Review', color: pendingApprovals > 0 ? 'text-warning-500' : 'text-neutral-400', key: 'approvals' }].map((card) => <div key={card.key} className="bg-surface-raised border border-surface-border rounded-xl p-4 hover:border-cyan-700/50 transition-all"><p className="text-[10px] text-neutral-400 uppercase tracking-wider mb-1">{card.label}</p><div className="flex items-end justify-between"><p className={`text-2xl font-bold text-white transition-all duration-300 ${flash[card.key] ? 'text-cyan-400 scale-110' : ''}`}>{card.value}</p><span className={`text-[10px] ${card.color} bg-surface-overlay px-2 py-0.5 rounded`}>{card.icon}</span></div></div>)}</div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5"><div className="bg-surface-raised border border-surface-border rounded-xl p-5"><div className="flex items-center justify-between mb-4"><h2 className="text-sm font-semibold text-white">Recent Activity</h2><Link to="/activity" className="text-[10px] text-cyan-400 hover:text-cyan-300">View all</Link></div>{activity.length ? <div className="space-y-2">{activity.map((item, i) => { const icon = ACTIVITY_ICONS[item.status] ?? ACTIVITY_ICONS.pending; return <div key={item.id ?? i} className="flex items-center gap-3 p-2.5 bg-surface-overlay rounded-lg"><span className={`w-7 h-7 rounded-lg flex items-center justify-center text-xs ${icon.color}`}>{icon.icon}</span><div className="min-w-0 flex-1"><p className="text-xs text-neutral-200 truncate">{item.action}</p><p className="text-[9px] text-neutral-500">{timeAgo(item.created_at)}</p></div></div> })}</div> : <p className="text-xs text-neutral-500">No recent activity</p>}</div><div className="bg-surface-raised border border-surface-border rounded-xl p-5"><h2 className="text-sm font-semibold text-white mb-4">System Summary</h2><div className="grid grid-cols-2 gap-3"><div className="p-3 bg-surface-overlay rounded-lg"><p className="text-[10px] text-neutral-500">Models</p><p className="text-lg font-bold text-white mt-1">{modelsLoaded}</p></div><div className="p-3 bg-surface-overlay rounded-lg"><p className="text-[10px] text-neutral-500">Services</p><p className="text-lg font-bold text-white mt-1">{servicesUp}/{servicesTotal}</p></div></div></div></div>
        </>
      )}
    </div>
  )
}
