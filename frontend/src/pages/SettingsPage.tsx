/**
 * Settings page — system configuration, user management.
 * Admin-only.
 */
import { useEffect, useState } from 'react'
import { settingsApi, SystemSettings, UserItem } from '../api/settings'
import { formatIST, formatISTDate } from '../utils/dates'
import { authApi } from '../api/auth'
import { useUIStore } from '../stores/uiStore'
import { useAuthStore } from '../stores/authStore'

// ------------------------------------------------------------------
// Settings form section
// ------------------------------------------------------------------
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white dark:bg-neutral-800 rounded-lg shadow-sm border border-neutral-200 dark:border-neutral-700 p-6">
      <h2 className="text-base font-semibold text-neutral-800 dark:text-neutral-100 mb-4">{title}</h2>
      {children}
    </div>
  )
}

function Field({ label, help, children }: { label: string; help?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 border-b border-neutral-100 dark:border-neutral-700 last:border-0">
      <div className="flex-1">
        <p className="text-sm font-medium text-neutral-700 dark:text-neutral-300">{label}</p>
        {help && <p className="text-xs text-neutral-400 mt-0.5">{help}</p>}
      </div>
      <div className="flex-shrink-0">{children}</div>
    </div>
  )
}

function NumberInput({ value, onChange, min, max }: {
  value: number; onChange: (v: number) => void; min: number; max: number
}) {
  return (
    <input type="number" value={value} min={min} max={max}
      onChange={e => onChange(Number(e.target.value))}
      className="w-24 text-sm border border-neutral-300 dark:border-neutral-600 rounded px-2 py-1 bg-white dark:bg-neutral-700 text-neutral-800 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
    />
  )
}

// ------------------------------------------------------------------
// User management section
// ------------------------------------------------------------------
function UsersSection() {
  const [users, setUsers] = useState<UserItem[]>([])
  const [loading, setLoading] = useState(true)
  const { addToast } = useUIStore()
  const { user: currentUser } = useAuthStore()

  const load = async () => {
    const u = await settingsApi.users().catch(() => [])
    setUsers(u)
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const handleRoleChange = async (userId: string, newRole: string) => {
    // Guard: prevent admin from demoting themselves if they are the only admin
    const adminCount = users.filter(u => u.role === 'admin').length
    const target = users.find(u => u.id === userId)
    if (target?.id === currentUser?.id && newRole !== 'admin' && adminCount <= 1) {
      addToast({ type: 'error', title: 'Cannot demote yourself', message: 'You are the only administrator. Promote another user first.' })
      return
    }

    try {
      await authApi.updateUser(userId, { role: newRole })
      setUsers(prev => prev.map(u => u.id === userId ? { ...u, role: newRole } : u))
      addToast({ type: 'success', title: 'Role updated' })
    } catch {
      addToast({ type: 'error', title: 'Failed to update role' })
    }
  }

  const handleToggleActive = async (userId: string, currentActive: boolean) => {
    if (userId === currentUser?.id) {
      addToast({ type: 'error', title: 'Cannot deactivate yourself' })
      return
    }
    try {
      await authApi.updateUser(userId, { is_active: !currentActive })
      setUsers(prev => prev.map(u => u.id === userId ? { ...u, is_active: !currentActive } : u))
      addToast({ type: 'success', title: currentActive ? 'User deactivated' : 'User reactivated' })
    } catch {
      addToast({ type: 'error', title: 'Failed to update user' })
    }
  }

  return (
    <Section title="User Management">
      {loading ? (
        <div className="animate-pulse space-y-2">
          {[...Array(2)].map((_, i) => <div key={i} className="h-10 bg-neutral-100 dark:bg-neutral-700 rounded" />)}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left border-b border-neutral-200 dark:border-neutral-700">
                <th className="pb-2 text-xs font-medium text-neutral-500 uppercase">User</th>
                <th className="pb-2 text-xs font-medium text-neutral-500 uppercase">Role</th>
                <th className="pb-2 text-xs font-medium text-neutral-500 uppercase">Status</th>
                <th className="pb-2 text-xs font-medium text-neutral-500 uppercase">Last Login</th>
                <th className="pb-2 text-xs font-medium text-neutral-500 uppercase sr-only">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100 dark:divide-neutral-700">
              {users.map(u => (
                <tr key={u.id} className="hover:bg-neutral-50 dark:hover:bg-neutral-700/30">
                  <td className="py-2.5">
                    <div>
                      <p className="font-medium text-neutral-800 dark:text-neutral-100">{u.username}</p>
                      <p className="text-xs text-neutral-400">{u.email}</p>
                    </div>
                  </td>
                  <td className="py-2.5">
                    <select value={u.role}
                      onChange={e => handleRoleChange(u.id, e.target.value)}
                      disabled={u.id === currentUser?.id}
                      className="text-xs border border-neutral-300 dark:border-neutral-600 rounded px-2 py-1 bg-white dark:bg-neutral-700 text-neutral-800 dark:text-neutral-100 disabled:opacity-50">
                      <option value="viewer">viewer</option>
                      <option value="analyst">analyst</option>
                      <option value="admin">admin</option>
                    </select>
                  </td>
                  <td className="py-2.5">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${
                      u.is_active ? 'bg-success-100 text-success-700' : 'bg-neutral-100 text-neutral-500'
                    }`}>{u.is_active ? 'active' : 'inactive'}</span>
                  </td>
                  <td className="py-2.5 text-xs text-neutral-400">
                    {u.last_login ? formatISTDate(u.last_login) : 'never'}
                  </td>
                  <td className="py-2.5">
                    {u.id !== currentUser?.id && (
                      <button onClick={() => handleToggleActive(u.id, u.is_active)}
                        className="text-xs text-neutral-500 hover:text-danger-600 transition-colors">
                        {u.is_active ? 'Deactivate' : 'Reactivate'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  )
}

// ------------------------------------------------------------------
// Main settings page
// ------------------------------------------------------------------
export default function SettingsPage() {
  const { addToast } = useUIStore()
  const [settings, setSettings] = useState<SystemSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    settingsApi.get()
      .then(s => { setSettings(s); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  const update = (key: keyof SystemSettings, value: number) => {
    if (settings) setSettings({ ...settings, [key]: value })
  }

  const handleSave = async () => {
    if (!settings) return
    setSaving(true)
    try {
      const saved = await settingsApi.update(settings)
      setSettings(saved)
      addToast({ type: 'success', title: 'Settings saved' })
    } catch (err: any) {
      const msg = err?.response?.data?.error?.message || 'Validation failed'
      addToast({ type: 'error', title: 'Save failed', message: msg })
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div className="flex justify-center py-12"><div className="animate-spin h-8 w-8 border-2 border-primary-600 border-t-transparent rounded-full" /></div>
  }

  if (!settings) {
    return <div className="text-center py-12 text-neutral-400">Could not load settings</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">Settings</h1>
          <p className="text-sm text-neutral-500 mt-1">System configuration — admin only</p>
        </div>
        <button onClick={handleSave} disabled={saving}
          className="px-5 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700 disabled:opacity-50">
          {saving ? 'Saving…' : 'Save All Settings'}
        </button>
      </div>

      {/* RAG section */}
      <Section title="📄 Document & RAG Settings">
        <Field label="Chunk size (tokens)" help="Size of each text chunk for embedding. 64–4096.">
          <NumberInput value={settings.default_chunk_size} onChange={v => update('default_chunk_size', v)} min={64} max={4096} />
        </Field>
        <Field label="Chunk overlap (tokens)" help="Overlap between adjacent chunks. 0–512.">
          <NumberInput value={settings.default_chunk_overlap} onChange={v => update('default_chunk_overlap', v)} min={0} max={512} />
        </Field>
        <Field label="Default top-k results" help="Number of chunks retrieved per RAG query. 1–20.">
          <NumberInput value={settings.default_top_k} onChange={v => update('default_top_k', v)} min={1} max={20} />
        </Field>
        <Field label="Score threshold" help="Minimum relevance score. 0.0–1.0.">
          <input type="number" step="0.05" min={0} max={1}
            value={settings.default_score_threshold}
            onChange={e => update('default_score_threshold', Number(e.target.value))}
            className="w-24 text-sm border border-neutral-300 dark:border-neutral-600 rounded px-2 py-1 bg-white dark:bg-neutral-700 text-neutral-800 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-primary-500" />
        </Field>
        <Field label="Max upload size (MB)" help="Maximum document file size. 1–500 MB.">
          <NumberInput value={settings.max_upload_size_mb} onChange={v => update('max_upload_size_mb', v)} min={1} max={500} />
        </Field>
      </Section>

      {/* Agent section */}
      <Section title="🤖 Agent Settings">
        <Field label="Default max iterations" help="Maximum reasoning steps per agent run. 1–20.">
          <NumberInput value={settings.default_max_iterations} onChange={v => update('default_max_iterations', v)} min={1} max={20} />
        </Field>
        <Field label="Approval timeout (minutes)" help="Time before pending approvals auto-expire. 1–60 min.">
          <NumberInput value={settings.approval_timeout_minutes} onChange={v => update('approval_timeout_minutes', v)} min={1} max={60} />
        </Field>
      </Section>

      {/* Sandbox section */}
      <Section title="🐳 Sandbox Settings">
        <Field label="Execution timeout (seconds)" help="Maximum time for sandboxed code execution. 5–300 s.">
          <NumberInput value={settings.sandbox_timeout_s} onChange={v => update('sandbox_timeout_s', v)} min={5} max={300} />
        </Field>
        <Field label="Memory limit (MB)" help="Container memory limit. 64–4096 MB.">
          <NumberInput value={settings.sandbox_mem_limit_mb} onChange={v => update('sandbox_mem_limit_mb', v)} min={64} max={4096} />
        </Field>
        <Field label="CPU quota" help="Docker CPU quota (50000 = 50% of one core). 10000–100000.">
          <NumberInput value={settings.sandbox_cpu_quota} onChange={v => update('sandbox_cpu_quota', v)} min={10000} max={100000} />
        </Field>
      </Section>

      {/* Users section */}
      <UsersSection />
    </div>
  )
}
