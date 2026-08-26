/**
 * Data page — Organizations & their data sources feeding the RAG system.
 * Isolation enforced server-side (404 on foreign orgs).
 */
import { useEffect, useState } from 'react'
import { dataApi, Organization, OrgDetail } from '../api/data'
import { useAuthStore } from '../stores/authStore'
import { useUIStore } from '../stores/uiStore'

const TYPE_ICON: Record<string, string> = {
  direct: '📝', file: '📄', location: '📁',
  database: '🗄', web: '🌐', api: '🔌',
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    indexed: 'bg-success-100 text-success-700',
    connected: 'bg-blue-100 text-blue-700',
    pending: 'bg-yellow-100 text-yellow-700',
    failed: 'bg-red-100 text-red-700',
    disabled: 'bg-neutral-100 text-neutral-500',
  }
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${colors[status] ?? colors.pending}`}>
      {status}
    </span>
  )
}

export default function DataPage() {
  const { user } = useAuthStore()
  const { addToast } = useUIStore()
  const isAdmin = user?.role === 'admin'
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [open, setOpen] = useState<OrgDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)
  // add-data modal
  const [modal, setModal] = useState<{ kind: string } | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)

  const load = async () => {
    try { setOrgs(await dataApi.listOrgs()) } catch { setOrgs([]) }
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  const openOrg = async (id: string) => setOpen(await dataApi.getOrg(id))

  const createOrg = async () => {
    if (!newName.trim()) return
    setCreating(true)
    try {
      await dataApi.createOrg(newName.trim())
      setNewName(''); await load()
      addToast({ type: 'success', title: 'Organization created' })
    } catch (e: any) {
      addToast({ type: 'error', title: e?.response?.data?.error?.message ?? 'Failed (analyst role required)' })
    } finally { setCreating(false) }
  }

  const submitSource = async () => {
    if (!open || !modal || !form.name?.trim()) return
    setBusy(true)
    try {
      if (modal.kind === 'direct') {
        const r = await dataApi.addDirect(open.id, form.title!, form.content!, form.tags?.split(','))
        addToast({ type: r.status === 'indexed' ? 'success' : 'error',
                   title: `Indexed: ${r.chunks} chunks`, message: r.error ?? '' })
      } else if (modal.kind === 'web') {
        const r = await dataApi.addWeb(open.id, form.url!, form.name)
        addToast({ type: r.status === 'indexed' ? 'success' : 'error',
                   title: `${r.chars} chars fetched`, message: `${r.chunks} chunks · ${r.status}` })
      } else if (modal.kind === 'database') {
        const src = await dataApi.addSource(open.id, 'database', form.name!, form)
        addToast({ type: src.note ? 'warning' as any : 'success',
                   title: `Status: ${src.status}`, message: src.note ?? '' })
      } else {
        const src = await dataApi.addSource(open.id, modal.kind, form.name!, form)
        addToast({ type: 'success', title: `Added (${src.status})`,
                   message: src.note ?? '' })
      }
      setModal(null); setForm({})
      setOpen(await dataApi.getOrg(open.id))
    } catch (e: any) {
      addToast({ type: 'error', title: 'Failed',
                 message: e?.response?.data?.detail ?? e?.message })
    } finally { setBusy(false) }
  }

  const sourceTypes = [
    { k: 'direct', label: '📝 Direct Data' },
    { k: 'file', label: '📄 File / Documents' },
    { k: 'location', label: '📁 Folder / Location' },
    { k: 'database', label: '🗄 Database' },
    { k: 'web', label: '🌐 Web / URL' },
    { k: 'api', label: '🔌 API' },
  ]

  return (
    <div className="space-y-6">
      {!open ? (
        <>
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">Data</h1>
              <p className="text-sm text-neutral-500 mt-1">
                Organizations and their data sources — isolated per organization
              </p>
            </div>
            {(isAdmin || user?.role === 'analyst') && (
              <div className="flex gap-2">
                <input value={newName} onChange={e => setNewName(e.target.value)}
                  placeholder="New organization name…" aria-label="Organization name"
                  className="rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm" />
                <button onClick={createOrg} disabled={creating || !newName.trim()}
                  className="px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700 disabled:opacity-50">
                  + Add Organization
                </button>
              </div>
            )}
          </div>

          {loading ? (
            <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
              {[...Array(3)].map((_, i) => <div key={i} className="h-32 bg-neutral-100 dark:bg-neutral-800 rounded-lg animate-pulse" />)}
            </div>
          ) : orgs.length === 0 ? (
            <div className="text-center py-16 text-neutral-400">
              <div className="text-4xl mb-2">🏢</div>
              <p>No organizations yet{isAdmin || user?.role !== 'viewer' ? ' — create one above' : ''}.</p>
            </div>
          ) : (
            <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
              {orgs.map(o => (
                <div key={o.id} className="bg-white dark:bg-neutral-800 rounded-lg border border-neutral-200 dark:border-neutral-700 p-5">
                  <div className="flex justify-between items-start mb-2">
                    <h3 className="font-semibold text-sm text-neutral-800 dark:text-neutral-100">{o.name}</h3>
                    <StatusBadge status={o.health} />
                  </div>
                  {o.description && <p className="text-xs text-neutral-500 mb-2">{o.description}</p>}
                  <p className="text-xs text-neutral-500">{o.source_count} sources · {o.doc_count} docs · {o.chunk_count} chunks</p>
                  <div className="flex gap-2 mt-3">
                    <button onClick={() => openOrg(o.id)}
                      className="text-xs px-3 py-1.5 bg-primary-600 text-white rounded-md hover:bg-primary-700">Open</button>
                    {(isAdmin || user?.role !== 'viewer') && (
                      <button onClick={async () => {
                        if (!window.confirm(`Delete "${o.name}" and all its data?`)) return
                        await dataApi.deleteOrg(o.id); await load()
                      }} className="text-xs px-3 py-1.5 border border-neutral-300 dark:border-neutral-600 rounded-md text-danger-600">Delete</button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      ) : (
        <>
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <button onClick={() => { setOpen(null); load() }}
                className="text-xs text-primary-600 hover:underline mb-1">← Back</button>
              <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">{open.name}</h1>
              <p className="text-sm text-neutral-500 mt-1">
                Created {open.created_at.slice(0, 10)} · {open.sources.length} sources · {open.documents.length} documents · {open.chunk_count} chunks
              </p>
            </div>
            {(isAdmin || user?.role !== 'viewer') && (
              <details className="relative">
                <summary className="cursor-pointer list-none px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700">+ Add Data</summary>
                <div className="absolute right-0 mt-1 w-56 bg-white dark:bg-neutral-800 rounded-md shadow-xl border border-neutral-200 dark:border-neutral-700 z-10">
                  {sourceTypes.map(s => (
                    <button key={s.k} onClick={() => setModal({ kind: s.k })}
                      className="block w-full text-left px-3 py-2 text-sm hover:bg-neutral-50 dark:hover:bg-neutral-700">
                      {s.label}
                    </button>
                  ))}
                </div>
              </details>
            )}
          </div>

          {/* Sources */}
          <section>
            <h2 className="text-sm font-semibold text-neutral-500 uppercase tracking-wider mb-2">Data Sources</h2>
            {open.sources.length === 0 ? <p className="text-xs text-neutral-400">No sources configured.</p> : (
              <div className="space-y-2">
                {open.sources.map(s => (
                  <div key={s.id} className="flex items-center justify-between bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-lg px-4 py-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">{TYPE_ICON[s.type]} {s.name}</p>
                      {s.last_error && <p className="text-[10px] text-warning-600">{s.last_error}</p>}
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0 ml-3">
                      <StatusBadge status={s.status} />
                      {(isAdmin || user?.role !== 'viewer') && (
                        <button onClick={async () => { await dataApi.deleteSource(open.id, s.id); setOpen(await dataApi.getOrg(open.id)) }}
                          className="text-xs text-danger-600">✕</button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Documents */}
          <section>
            <h2 className="text-sm font-semibold text-neutral-500 uppercase tracking-wider mb-2">Indexed Documents</h2>
            {open.documents.length === 0 ? <p className="text-xs text-neutral-400">Nothing indexed yet.</p> : (
              <table className="w-full text-xs">
                <thead><tr className="text-left text-neutral-400">
                  <th className="py-1">File</th><th>Status</th><th>Chunks</th><th>Size</th>
                </tr></thead>
                <tbody>
                  {open.documents.map(d => (
                    <tr key={d.id} className="border-t border-neutral-100 dark:border-neutral-700">
                      <td className="py-1.5 font-mono">{d.name}</td>
                      <td><StatusBadge status={d.status} /></td>
                      <td>{d.chunks}</td>
                      <td>{(d.size / 1024).toFixed(1)} KB</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          {/* Add-data modal */}
          {modal && (
            <div className="fixed inset-0 bg-black/50 z-40 flex items-center justify-center p-4">
              <div className="bg-white dark:bg-neutral-800 rounded-lg shadow-xl w-full max-w-lg" role="dialog">
                <div className="flex justify-between items-center p-5 border-b border-neutral-200 dark:border-neutral-700">
                  <h3 className="font-semibold">{sourceTypes.find(s => s.k === modal.kind)?.label}</h3>
                  <button onClick={() => setModal(null)}>✕</button>
                </div>
                <div className="p-5 space-y-3 max-h-[65vh] overflow-y-auto">
                  {modal.kind !== 'direct' && (
                    <input placeholder="Name" value={form.name ?? ''} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                      className="w-full rounded border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm" />
                  )}
                  {modal.kind === 'direct' && (<>
                    <input placeholder="Title" value={form.title ?? ''} onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                      className="w-full rounded border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm" />
                    <textarea rows={7} placeholder="Content…" value={form.content ?? ''} onChange={e => setForm(f => ({ ...f, content: e.target.value }))}
                      className="w-full rounded border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm font-mono" />
                    <input placeholder="Tags (comma-separated)" value={form.tags ?? ''} onChange={e => setForm(f => ({ ...f, tags: e.target.value }))}
                      className="w-full rounded border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm" />
                  </>)}
                  {modal.kind === 'web' && (
                    <input placeholder="https://example.com/page" value={form.url ?? ''} onChange={e => setForm(f => ({ ...f, url: e.target.value }))}
                      className="w-full rounded border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm font-mono" />
                  )}
                  {modal.kind === 'location' && (
                    <input placeholder="Path (must match DATA_LOCATIONS allowlist)" value={form.path ?? ''} onChange={e => setForm(f => ({ ...f, path: e.target.value }))}
                      className="w-full rounded border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm font-mono" />
                  )}
                  {modal.kind === 'database' && (<>
                    <select value={form.type ?? ''} onChange={e => setForm(f => ({ ...f, type: e.target.value }))}
                      className="w-full rounded border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm">
                      <option value="">Select engine…</option>
                      <option value="sqlite">SQLite</option>
                      <option value="postgresql">PostgreSQL (driver unavailable)</option>
                      <option value="mysql">MySQL (driver unavailable)</option>
                    </select>
                    {form.type === 'sqlite' && (
                      <input placeholder="Absolute path to .db file" value={form.path ?? ''} onChange={e => setForm(f => ({ ...f, path: e.target.value }))}
                        className="w-full rounded border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm font-mono" />
                    )}
                  </>)}
                  {modal.kind === 'api' && (<>
                    <input placeholder="Base URL" value={form.url ?? ''} onChange={e => setForm(f => ({ ...f, url: e.target.value }))}
                      className="w-full rounded border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm font-mono" />
                    <input placeholder="API Key (stored masked)" type="password" value={form.api_key ?? ''} onChange={e => setForm(f => ({ ...f, api_key: e.target.value }))}
                      className="w-full rounded border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm" />
                  </>)}
                </div>
                <div className="flex justify-end gap-2 p-5 border-t border-neutral-200 dark:border-neutral-700">
                  <button onClick={() => setModal(null)} className="px-3 py-2 text-sm border border-neutral-300 dark:border-neutral-600 rounded-md">Cancel</button>
                  <button onClick={submitSource} disabled={busy}
                    className="px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700 disabled:opacity-50">
                    {busy ? 'Working…' : modal.kind === 'direct' || modal.kind === 'web' ? 'Save & Index' : 'Save'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
