/**
 * System health status pill shown in the top bar.
 * Polls /api/v1/system/status every 30 seconds.
 */
import { useEffect, useState } from 'react'
import { systemApi, SystemStatus } from '../../api/system'
import { useAuthStore } from '../../stores/authStore'

export default function StatusPill() {
  const { accessToken } = useAuthStore()
  const [status, setStatus] = useState<string | null>(null)

  const poll = async () => {
    if (!accessToken) return
    try {
      const s = await systemApi.status()
      setStatus(s.status)
    } catch {
      setStatus('unhealthy')
    }
  }

  useEffect(() => {
    poll()
    const id = setInterval(poll, 30_000)
    return () => clearInterval(id)
  }, [accessToken])

  if (!accessToken || !status) return null

  const cfg: Record<string, { label: string; cls: string }> = {
    healthy:   { label: 'System Healthy',   cls: 'bg-success-100 text-success-700 border border-success-200' },
    degraded:  { label: 'System Degraded',  cls: 'bg-warning-100 text-warning-700 border border-warning-200' },
    unhealthy: { label: 'System Unhealthy', cls: 'bg-danger-100  text-danger-700  border border-danger-200' },
  }
  const { label, cls } = cfg[status] ?? cfg['unhealthy']

  return (
    <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-medium ${cls}`}>
      <span aria-hidden="true">●</span>
      {label}
    </span>
  )
}
