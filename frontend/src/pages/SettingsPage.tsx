import { useEffect, useState } from 'react'
import { settingsApi, SystemSettings, UserItem } from '../api/settings'
import { authApi } from '../api/auth'
import { useAuthStore } from '../stores/authStore'
import { useUIStore } from '../stores/uiStore'
import { Card, CardHeader, CardContent } from '../components/ui/Card'
import Badge from '../components/ui/Badge'

export default function SettingsPage() {
  const { user } = useAuthStore()
  const { addToast } = useUIStore()
  const isAdmin = user?.role === 'admin'
  const [settings, setSettings] = useState<SystemSettings | null>(null)
  const [users, setUsers] = useState<UserItem[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [tab, setTab] = useState<'system' | 'users'>('system')
  const [editing, setEditing] = useState<UserItem | null>(null)
  const [editRole, setEditRole] = useState('viewer')
  const [editActive, setEditActive] = useState(true)
  const [busyUserId, setBusyUserId] = useState<string | null>(null)

  const loadUsers = async () => {
    if (!isAdmin) return
    try {
      setUsers(await settingsApi.users())
    } catch {
      addToast({ type: 'error', title: 'Unable to load users' })
    }
  }

  useEffect(() => {
    const load = async () => {
      const requests: Promise<unknown>[] = [settingsApi.get()]
      if (isAdmin) requests.push(settingsApi.users())
      const results = await Promise.allSettled(requests)
      if (results[0].status === 'fulfilled') setSettings(results[0].value as SystemSettings)
      if (isAdmin && results[1]?.status === 'fulfilled') setUsers(results[1].value as UserItem[])
      setLoading(false)
    }
    load()
  }, [isAdmin])

  const handleSave = async () => {
    if (!settings) return
    setSaving(true)
    try {
      await settingsApi.update(settings)
      addToast({ type: 'success', title: 'Settings saved' })
    } catch { addToast({ type: 'error', title: 'Save failed' }) }
    setSaving(false)
  }

  const startEdit = (u: UserItem) => {
    setEditing(u)
    setEditRole(u.role)
    setEditActive(u.is_active)
  }

  const saveUser = async () => {
    if (!editing) return
    setBusyUserId(editing.id)
    try {
      await authApi.updateUser(editing.id, { role: editRole, is_active: editActive })
      addToast({ type: 'success', title: 'User updated' })
      setEditing(null)
      await loadUsers()
    } catch { addToast({ type: 'error', title: 'User update failed' }) }
    setBusyUserId(null)
  }

  const deleteUser = async (u: UserItem) => {
    if (u.id === user?.id) {
      addToast({ type: 'error', title: 'You cannot delete your own admin account' })
      return
    }
    if (!window.confirm(`Delete user ${u.username || u.email}? This cannot be undone.`)) return
    setBusyUserId(u.id)
    try {
      await authApi.deleteUser(u.id)
      addToast({ type: 'success', title: 'User deleted' })
      setUsers(current => current.filter(item => item.id !== u.id))
    } catch { addToast({ type: 'error', title: 'User deletion failed' }) }
    setBusyUserId(null)
  }

  const inputCls = "w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:ring-2 focus:ring-cyan-500"

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg md:text-2xl font-bold text-white">Settings</h1>
        <p className="text-xs md:text-sm text-neutral-400 mt-1">Configure system settings and manage users.</p>
      </div>

      <div className="flex gap-2">
        <button onClick={() => setTab('system')} className={`px-4 py-2 text-sm rounded-lg border transition-colors ${tab === 'system' ? 'bg-cyan-600 text-white border-cyan-600' : 'border-surface-border text-neutral-400 hover:bg-surface-muted'}`}>System</button>
        {isAdmin && <button onClick={() => setTab('users')} className={`px-4 py-2 text-sm rounded-lg border transition-colors ${tab === 'users' ? 'bg-cyan-600 text-white border-cyan-600' : 'border-surface-border text-neutral-400 hover:bg-surface-muted'}`}>Users ({users.length})</button>}
      </div>

      {loading ? (
        <div className="space-y-4">{[...Array(3)].map((_, i) => <div key={i} className="skeleton h-24" />)}</div>
      ) : tab === 'system' ? (
        settings && (
          <Card>
            <CardHeader><h2 className="text-sm font-semibold text-white">System Configuration</h2></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div><label className="block text-xs text-neutral-400 mb-1">Chunk Size</label><input type="number" value={settings.default_chunk_size} onChange={e => setSettings({ ...settings, default_chunk_size: +e.target.value })} className={inputCls} /></div>
                <div><label className="block text-xs text-neutral-400 mb-1">Chunk Overlap</label><input type="number" value={settings.default_chunk_overlap} onChange={e => setSettings({ ...settings, default_chunk_overlap: +e.target.value })} className={inputCls} /></div>
                <div><label className="block text-xs text-neutral-400 mb-1">Default Top-K</label><input type="number" value={settings.default_top_k} onChange={e => setSettings({ ...settings, default_top_k: +e.target.value })} className={inputCls} /></div>
                <div><label className="block text-xs text-neutral-400 mb-1">Score Threshold</label><input type="number" step="0.1" value={settings.default_score_threshold} onChange={e => setSettings({ ...settings, default_score_threshold: +e.target.value })} className={inputCls} /></div>
                <div><label className="block text-xs text-neutral-400 mb-1">Max Agent Iterations</label><input type="number" value={settings.default_max_iterations} onChange={e => setSettings({ ...settings, default_max_iterations: +e.target.value })} className={inputCls} /></div>
                <div><label className="block text-xs text-neutral-400 mb-1">Approval Timeout (min)</label><input type="number" value={settings.approval_timeout_minutes} onChange={e => setSettings({ ...settings, approval_timeout_minutes: +e.target.value })} className={inputCls} /></div>
                <div><label className="block text-xs text-neutral-400 mb-1">Sandbox Timeout (s)</label><input type="number" value={settings.sandbox_timeout_s} onChange={e => setSettings({ ...settings, sandbox_timeout_s: +e.target.value })} className={inputCls} /></div>
                <div><label className="block text-xs text-neutral-400 mb-1">Sandbox Memory (MB)</label><input type="number" value={settings.sandbox_mem_limit_mb} onChange={e => setSettings({ ...settings, sandbox_mem_limit_mb: +e.target.value })} className={inputCls} /></div>
                <div><label className="block text-xs text-neutral-400 mb-1">Max Upload Size (MB)</label><input type="number" value={settings.max_upload_size_mb} onChange={e => setSettings({ ...settings, max_upload_size_mb: +e.target.value })} className={inputCls} /></div>
              </div>
              <button onClick={handleSave} disabled={saving} className="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-medium hover:bg-cyan-500 disabled:opacity-50">{saving ? 'Saving...' : 'Save Settings'}</button>
            </CardContent>
          </Card>
        )
      ) : (
        <Card>
          <CardHeader><h2 className="text-sm font-semibold text-white">Users</h2></CardHeader>
          <CardContent>
            {users.length === 0 ? <p className="text-sm text-neutral-500 text-center py-8">No users found.</p> : (
              <div className="space-y-2">
                {users.map(u => (
                  <div key={u.id} className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 p-3 bg-surface-overlay rounded-lg border border-surface-border">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-gradient-to-br from-cyan-600 to-cyan-800 flex items-center justify-center text-xs text-white font-medium border border-cyan-500/30">{(u.username || u.email || 'U')[0].toUpperCase()}</div>
                      <div><p className="text-sm text-neutral-200">{u.username || u.email}</p><p className="text-[10px] text-neutral-500">{u.email}</p></div>
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge variant={u.role === 'admin' ? 'cyan' : 'default'} size="sm">{u.role}</Badge>
                      <Badge variant={u.is_active ? 'success' : 'danger'} size="sm">{u.is_active ? 'active' : 'inactive'}</Badge>
                      {u.id !== user?.id && <>
                        <button onClick={() => startEdit(u)} disabled={busyUserId === u.id} className="px-3 py-1.5 text-xs rounded-md border border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/10 disabled:opacity-50">Edit</button>
                        <button onClick={() => deleteUser(u)} disabled={busyUserId === u.id} className="px-3 py-1.5 text-xs rounded-md border border-red-500/40 text-red-300 hover:bg-red-500/10 disabled:opacity-50">Delete</button>
                      </>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true">
          <div className="w-full max-w-md rounded-xl border border-surface-border bg-surface p-5 shadow-xl">
            <div className="flex items-center justify-between mb-4"><div><h3 className="text-base font-semibold text-white">Edit User</h3><p className="text-xs text-neutral-500 mt-1">{editing.email}</p></div><button onClick={() => setEditing(null)} className="text-neutral-400 hover:text-white">✕</button></div>
            <div className="space-y-4">
              <div><label className="block text-xs text-neutral-400 mb-1">Role</label><select value={editRole} onChange={e => setEditRole(e.target.value)} className={inputCls}><option value="admin">Admin</option><option value="analyst">Analyst</option><option value="viewer">Viewer</option></select></div>
              <label className="flex items-center gap-2 text-sm text-neutral-300"><input type="checkbox" checked={editActive} onChange={e => setEditActive(e.target.checked)} /> Active account</label>
              <div className="flex justify-end gap-2"><button onClick={() => setEditing(null)} className="px-4 py-2 text-sm rounded-lg border border-surface-border text-neutral-300">Cancel</button><button onClick={saveUser} disabled={busyUserId === editing.id} className="px-4 py-2 text-sm rounded-lg bg-cyan-600 text-white hover:bg-cyan-500 disabled:opacity-50">{busyUserId === editing.id ? 'Saving...' : 'Save Changes'}</button></div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
