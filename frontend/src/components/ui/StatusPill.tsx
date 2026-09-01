import { useEffect, useState } from 'react'
import { systemApi, SystemStatus } from '../../api/system'
import { useAuthStore } from '../../stores/authStore'

export default function StatusPill() {
  const { accessToken } = useAuthStore()
  const [status, setStatus] = useState<string | null>(null)

  const poll = async () => {
    if (!accessToken) return
    try { const s = await systemApi.status(); setStatus(s.status) }
    catch { setStatus('unhealthy') }
  }

  useEffect(() => { poll(); const id = setInterval(poll, 30_000); return () => clearInterval(id) }, [accessToken])

  if (!accessToken || !status) return null

  const cfg: Record<string, { label: string; cls: string }> = {
    healthy:   { label: 'System Operational', cls: 'bg-success-500/15 text-success-500 border border-success-500/30' },
    degraded:  { label: 'System Degraded',    cls: 'bg-warning-500/15 text-warning-500 border border-warning-500/30' },
    unhealthy: { label: 'System Unhealthy',   cls: 'bg-danger-500/15 text-danger-500 border border-danger-500/30' },
  }
  const { label, cls } = cfg[status] ?? cfg['unhealthy']

  return (
    <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-medium ${cls}`}>
      <span className="relative flex h-2 w-2">
        <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
          status === 'healthy' ? 'bg-success-500' : status === 'degraded' ? 'bg-warning-500' : 'bg-danger-500'
        }`} />
        <span className={`relative inline-flex rounded-full h-2 w-2 ${
          status === 'healthy' ? 'bg-success-500' : status === 'degraded' ? 'bg-warning-500' : 'bg-danger-500'
        }`} />
      </span>
      {label}
    </span>
  )
}
