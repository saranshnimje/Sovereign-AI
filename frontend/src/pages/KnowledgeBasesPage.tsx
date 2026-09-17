import { useEffect, useState, useRef } from 'react'
import { knowledgeBasesApi, KnowledgeBase, Document } from '../api/knowledgeBases'
import { useAuthStore } from '../stores/authStore'
import { useUIStore } from '../stores/uiStore'
import Badge from '../components/ui/Badge'
import DocumentPreviewModal from '../components/documents/DocumentPreviewModal'

export default function KnowledgeBasesPage() {
  const { user } = useAuthStore()
  const { addToast } = useUIStore()
  const isAdmin = user?.role === 'admin'
  const [kbs, setKbs] = useState<KnowledgeBase[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [selectedKB, setSelectedKB] = useState<KnowledgeBase | null>(null)
  const [documents, setDocuments] = useState<Document[]>([])
  const [loadingDocs, setLoadingDocs] = useState(false)
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const [previewDoc, setPreviewDoc] = useState<Document | null>(null)

  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [creating, setCreating] = useState(false)

  const load = async () => {
    try { const data = await knowledgeBasesApi.list(); setKbs(data) }
    catch { /* ignore */ }
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  const preferDocument = (a: Document, b: Document) => {
    const rank: Record<string, number> = { indexed: 4, processing: 3, failed: 2, pending: 1 }
    return (rank[a.status] || 0) >= (rank[b.status] || 0) ? a : b
  }

  const dedupeDocuments = (docs: Document[]) => {
    const byName = new Map<string, Document>()
    for (const doc of docs) {
      const key = doc.original_name.trim().toLowerCase()
      const existing = byName.get(key)
      byName.set(key, existing ? preferDocument(existing, doc) : doc)
    }
    return Array.from(byName.values()).sort((a, b) => b.created_at.localeCompare(a.created_at))
  }

  const loadDocs = async (kb: KnowledgeBase) => {
    setSelectedKB(kb)
    setLoadingDocs(true)
    try {
      const docs = await knowledgeBasesApi.listDocuments(kb.id)
      setDocuments(dedupeDocuments(docs))
    } catch { setDocuments([]) }
    setLoadingDocs(false)
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setCreating(true)
    try {
      const kb = await knowledgeBasesApi.create({ name: newName, description: newDesc })
      setKbs(prev => [...prev, kb])
      setShowCreate(false)
      setNewName(''); setNewDesc('')
      addToast({ type: 'success', title: 'Knowledge Base created', message: kb.name })
    } catch (err: any) {
      addToast({ type: 'error', title: 'Failed', message: err?.response?.data?.detail || 'Create failed' })
    }
    setCreating(false)
  }

  const handleDelete = async (kb: KnowledgeBase) => {
    if (!window.confirm(`Delete "${kb.name}"? This will remove all documents.`)) return
    try {
      await knowledgeBasesApi.delete(kb.id)
      setKbs(prev => prev.filter(x => x.id !== kb.id))
      if (selectedKB?.id === kb.id) setSelectedKB(null)
      addToast({ type: 'info', title: 'Deleted' })
    } catch { addToast({ type: 'error', title: 'Delete failed' }) }
  }

  const handleDeleteDocument = async (doc: Document) => {
    if (!selectedKB || !window.confirm(`Delete "${doc.original_name}"?`)) return
    try {
      await knowledgeBasesApi.deleteDocument(selectedKB.id, doc.id)
      setDocuments(prev => prev.filter(x => x.id !== doc.id))
      setKbs(prev => prev.map(k => k.id === selectedKB.id ? { ...k, doc_count: Math.max(0, k.doc_count - 1), chunk_count: Math.max(0, k.chunk_count - (doc.chunk_count || 0)) } : k))
      if (previewDoc?.id === doc.id) setPreviewDoc(null)
      addToast({ type: 'info', title: 'Document deleted', message: doc.original_name })
    } catch (err: any) {
      addToast({ type: 'error', title: 'Delete failed', message: err?.response?.data?.detail || 'Could not delete document' })
    }
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !selectedKB) return
    const existing = documents.find(d => d.original_name.trim().toLowerCase() === file.name.trim().toLowerCase())
    if (existing && existing.status === 'indexed') {
      addToast({ type: 'info', title: 'Already uploaded', message: `${file.name} is already indexed in this knowledge base.` })
      if (fileRef.current) fileRef.current.value = ''
      return
    }
    setUploading(true)
    try {
      const doc = await knowledgeBasesApi.uploadDocument(selectedKB.id, file)
      setDocuments(prev => dedupeDocuments([...prev, doc]))
      setKbs(prev => prev.map(k => k.id === selectedKB.id ? { ...k, doc_count: k.doc_count + 1 } : k))
      addToast({ type: 'success', title: 'Uploaded', message: file.name })
    } catch (err: any) {
      addToast({ type: 'error', title: 'Upload failed', message: err?.response?.data?.detail || 'Upload error' })
    }
    setUploading(false)
    if (fileRef.current) fileRef.current.value = ''
  }

  const statusColors: Record<string, string> = {
    completed: 'success', processing: 'warning', pending: 'info', indexed: 'success', failed: 'danger',
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-lg md:text-2xl font-bold text-white">Knowledge Bases</h1>
          <p className="text-xs md:text-sm text-neutral-400 mt-1">Manage knowledge bases and documents for RAG-powered AI.</p>
        </div>
        {isAdmin && (
          <button onClick={() => setShowCreate(true)} className="px-3 md:px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-medium hover:bg-cyan-500 transition-colors">
            + Create Knowledge Base
          </button>
        )}
      </div>

      {showCreate && (
        <div className="bg-surface-raised border border-surface-border rounded-xl p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Create Knowledge Base</h2>
          <form onSubmit={handleCreate} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-neutral-300 mb-1">Name</label>
              <input type="text" value={newName} onChange={e => setNewName(e.target.value)} required
                className="w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:ring-2 focus:ring-cyan-500" />
            </div>
            <div>
              <label className="block text-sm font-medium text-neutral-300 mb-1">Description</label>
              <input type="text" value={newDesc} onChange={e => setNewDesc(e.target.value)}
                className="w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-neutral-200 focus:outline-none focus:ring-2 focus:ring-cyan-500" />
            </div>
            <div className="flex gap-2">
              <button type="submit" disabled={creating || !newName.trim()} className="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-medium hover:bg-cyan-500 disabled:opacity-50">
                {creating ? 'Creating...' : 'Create'}
              </button>
              <button type="button" onClick={() => setShowCreate(false)} className="px-4 py-2 border border-surface-border text-neutral-300 rounded-lg text-sm hover:bg-surface-muted">
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => <div key={i} className="skeleton h-32" />)}
        </div>
      ) : kbs.length === 0 ? (
        <div className="bg-surface-raised border border-surface-border rounded-xl p-12 text-center">
          <div className="w-16 h-16 rounded-2xl bg-cyan-500/10 flex items-center justify-center text-3xl mx-auto mb-4">
            <svg className="w-8 h-8 text-cyan-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0118 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-white mb-2">No Knowledge Bases</h3>
          <p className="text-sm text-neutral-400 mb-4">Create a knowledge base to start uploading documents for RAG.</p>
          {isAdmin && (
            <button onClick={() => setShowCreate(true)} className="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-medium hover:bg-cyan-500">
              + Create First Knowledge Base
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {kbs.map(kb => (
            <div key={kb.id} className="bg-surface-raised border border-surface-border rounded-xl p-5 hover:border-cyan-700/50 transition-all cursor-pointer"
              onClick={() => loadDocs(kb)}>
              <div className="flex items-start justify-between mb-3">
                <h3 className="font-semibold text-white text-sm">{kb.name}</h3>
                {isAdmin && (
                  <button onClick={(e) => { e.stopPropagation(); handleDelete(kb) }}
                    className="text-xs text-neutral-500 hover:text-danger-500 transition-colors">Delete</button>
                )}
              </div>
              {kb.description && <p className="text-xs text-neutral-400 mb-3">{kb.description}</p>}
              <div className="flex gap-4 text-xs text-neutral-500">
                <span>{kb.doc_count} docs</span>
                <span>{kb.chunk_count} chunks</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedKB && (
        <div className="bg-surface-raised border border-surface-border rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-white">{selectedKB.name} - Documents</h2>
            <div className="flex gap-2">
              <input ref={fileRef} type="file" className="hidden" onChange={handleUpload} accept=".pdf,.docx,.txt,.csv,.md,.markdown,.json,.yaml,.yml" />
              <button onClick={() => fileRef.current?.click()} disabled={uploading}
                className="px-3 py-1.5 bg-cyan-600 text-white rounded-lg text-xs font-medium hover:bg-cyan-500 disabled:opacity-50">
                {uploading ? 'Uploading...' : '+ Upload Document'}
              </button>
              <button onClick={() => setSelectedKB(null)} className="text-xs text-neutral-500 hover:text-neutral-300">Close</button>
            </div>
          </div>
          {loadingDocs ? (
            <div className="flex justify-center py-8"><div className="animate-spin h-6 w-6 border-2 border-cyan-500 border-t-transparent rounded-full" /></div>
          ) : documents.length === 0 ? (
            <p className="text-sm text-neutral-500 text-center py-8">No documents uploaded yet.</p>
          ) : (
            <div className="space-y-2">
              {documents.map(doc => (
                <div
                  key={doc.id}
                  className="flex items-center justify-between p-3 bg-surface-overlay rounded-lg border border-surface-border hover:border-cyan-700/50 transition-all"
                >
                  <button onClick={() => setPreviewDoc(doc)} className="flex items-center gap-3 min-w-0 text-left flex-1">
                    <span className="text-sm">{doc.mime_type === 'application/pdf' ? '📄' : doc.mime_type === 'text/csv' ? '📊' : '📝'}</span>
                    <span className="min-w-0">
                      <p className="text-sm text-neutral-200 truncate">{doc.original_name}</p>
                      <p className="text-[10px] text-neutral-500">{doc.page_count || 0} pages, {doc.chunk_count || 0} chunks</p>
                    </span>
                  </button>
                  <div className="flex items-center gap-2 ml-3">
                    <Badge variant={statusColors[doc.status] as any || 'default'} size="sm">{doc.status}</Badge>
                    <button onClick={() => handleDeleteDocument(doc)} className="text-[10px] text-neutral-500 hover:text-red-400">Delete</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {previewDoc && (
        <DocumentPreviewModal document={previewDoc} onClose={() => setPreviewDoc(null)} />
      )}
    </div>
  )
}
