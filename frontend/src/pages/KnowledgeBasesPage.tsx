/**
 * Knowledge Bases list page — shows all KBs, create new, open detail.
 */
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { kbApi, KBResponse } from '../api/documents'
import { formatIST, formatISTDate } from '../utils/dates'
import { useUIStore } from '../stores/uiStore'

function CreateKBModal({ onClose, onCreate }: { onClose: () => void; onCreate: (kb: KBResponse) => void }) {
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { addToast } = useUIStore()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const kb = await kbApi.create({ name, description: desc || undefined })
      addToast({ type: 'success', title: 'Knowledge base created', message: kb.name })
      onCreate(kb)
      onClose()
    } catch (err: any) {
      setError(err?.response?.data?.error?.message || err?.response?.data?.detail || 'Failed to create')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-40 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-neutral-800 rounded-lg shadow-xl w-full max-w-md" role="dialog" aria-modal="true" aria-labelledby="create-kb-title">
        <div className="flex items-center justify-between p-6 border-b border-neutral-200 dark:border-neutral-700">
          <h2 id="create-kb-title" className="text-lg font-semibold text-neutral-800 dark:text-neutral-100">New Knowledge Base</h2>
          <button onClick={onClose} className="text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-200" aria-label="Close">✕</button>
        </div>
        <form onSubmit={submit}>
          <div className="p-6 space-y-4">
            {error && <div className="text-sm text-danger-600 bg-danger-50 border border-danger-200 rounded p-3" role="alert">{error}</div>}
            <div>
              <label htmlFor="kb-name" className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Name <span className="text-danger-500" aria-hidden="true">*</span>
              </label>
              <input
                id="kb-name" type="text" value={name} onChange={e => setName(e.target.value)}
                required maxLength={100} placeholder="e.g. Policy Documents 2026"
                className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
            </div>
            <div>
              <label htmlFor="kb-desc" className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">Description</label>
              <textarea
                id="kb-desc" value={desc} onChange={e => setDesc(e.target.value)}
                rows={2} placeholder="Optional description"
                className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
            </div>
          </div>
          <div className="flex justify-end gap-3 p-6 border-t border-neutral-200 dark:border-neutral-700">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm font-medium text-neutral-700 dark:text-neutral-300 bg-white dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md hover:bg-neutral-50">Cancel</button>
            <button type="submit" disabled={loading || !name.trim()}
              className="px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-md hover:bg-primary-700 disabled:opacity-50">
              {loading ? 'Creating…' : 'Create Knowledge Base'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function KnowledgeBasesPage() {
  const [kbs, setKbs] = useState<KBResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    kbApi.list().then(setKbs).catch(() => {}).finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">Knowledge Bases</h1>
          <p className="text-sm text-neutral-500 mt-1">Index your documents for AI-powered search and Q&amp;A</p>
        </div>
        <button onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700 transition-colors">
          + New Knowledge Base
        </button>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => <div key={i} className="bg-neutral-100 dark:bg-neutral-800 rounded-lg h-32 animate-pulse" />)}
        </div>
      ) : kbs.length === 0 ? (
        <div className="flex flex-col items-center justify-center min-h-64 text-center">
          <div className="text-4xl mb-3" aria-hidden="true">🧠</div>
          <p className="text-neutral-600 dark:text-neutral-400 font-medium">No knowledge bases yet</p>
          <p className="text-sm text-neutral-400 mt-1">Create one to start indexing your documents</p>
          <button onClick={() => setShowCreate(true)}
            className="mt-4 px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700">
            + New Knowledge Base
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {kbs.map(kb => (
            <button key={kb.id} onClick={() => navigate(`/knowledge-bases/${kb.id}`)}
              className="text-left bg-white dark:bg-neutral-800 rounded-lg shadow-sm border border-neutral-200 dark:border-neutral-700 p-5 hover:shadow-md hover:border-primary-300 transition-all">
              <div className="flex items-start justify-between mb-2">
                <span className="text-2xl" aria-hidden="true">🧠</span>
                <span className="text-xs text-neutral-400">{formatISTDate(kb.created_at)}</span>
              </div>
              <h3 className="font-semibold text-neutral-800 dark:text-neutral-100 text-sm truncate">{kb.name}</h3>
              {kb.description && <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-1 line-clamp-2">{kb.description}</p>}
              <div className="flex gap-4 mt-3">
                <span className="text-xs text-neutral-500"><strong>{kb.doc_count}</strong> docs</span>
                <span className="text-xs text-neutral-500"><strong>{kb.chunk_count}</strong> chunks</span>
              </div>
            </button>
          ))}
        </div>
      )}

      {showCreate && (
        <CreateKBModal
          onClose={() => setShowCreate(false)}
          onCreate={kb => setKbs(prev => [kb, ...prev])}
        />
      )}
    </div>
  )
}
