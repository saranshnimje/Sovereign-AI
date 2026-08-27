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
    healthy:   { label: 'System Healthy',   cls: 'bg-green-900/40 text-green-400 border border-green-800/40' },
    degraded:  { label: 'System Degraded',  cls: 'bg-yellow-900/40 text-yellow-400 border border-yellow-800/40' },
    unhealthy: { label: 'System Unhealthy', cls: 'bg-red-900/40 text-red-400 border border-red-800/40' },
  }
  const { label, cls } = cfg[status] ?? cfg['unhealthy']

  return (
    <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-medium ${cls}`}>
      <span aria-hidden="true">●</span>
      {label}
    </span>
  )
}
