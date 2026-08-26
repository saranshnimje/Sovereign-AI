/**
 * Knowledge Base detail page — document list, upload, RAG query.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { documentsApi, DocumentResponse, kbApi, KBQueryResponse, KBQuerySource, KBResponse } from '../api/documents'
import { formatIST, formatISTDate } from '../utils/dates'
import { useAuthStore } from '../stores/authStore'
import { useUIStore } from '../stores/uiStore'

// ------------------------------------------------------------------
// Processing status badge
// ------------------------------------------------------------------
function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, string> = {
    pending:    'bg-neutral-100 text-neutral-600',
    processing: 'bg-blue-100 text-blue-700',
    indexed:    'bg-success-100 text-success-700',
    failed:     'bg-danger-100 text-danger-600',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cfg[status] || cfg.pending}`}>
      {status}
    </span>
  )
}

// ------------------------------------------------------------------
// Upload modal
// ------------------------------------------------------------------
function UploadModal({
  kbId,
  onClose,
  onUploaded,
}: { kbId: string; onClose: () => void; onUploaded: (doc: DocumentResponse) => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [runOcr, setRunOcr] = useState(true)
  const [dragging, setDragging] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { addToast } = useUIStore()

  const ALLOWED_TYPES = ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'text/plain', 'text/csv', 'image/png', 'image/jpeg']
  const MAX_MB = 50

  const validate = (f: File): string | null => {
    if (f.size === 0) return 'File is empty'
    if (f.size > MAX_MB * 1024 * 1024) return `File exceeds ${MAX_MB} MB limit`
    const ext = f.name.split('.').pop()?.toLowerCase()
    const allowed = ['pdf', 'docx', 'txt', 'md', 'csv', 'png', 'jpg', 'jpeg']
    if (!ext || !allowed.includes(ext)) return `Extension .${ext} is not allowed`
    return null
  }

  const pick = (f: File) => {
    const err = validate(f)
    if (err) { setError(err); setFile(null) }
    else { setError(''); setFile(f) }
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) return
    setLoading(true)
    setError('')
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('kb_id', kbId)
      fd.append('run_ocr', String(runOcr))
      const doc = await documentsApi.upload(fd)
      addToast({ type: 'success', title: 'Document uploaded', message: `Processing ${doc.original_name}…` })
      onUploaded(doc)
      onClose()
    } catch (err: any) {
      setError(err?.response?.data?.error?.message || 'Upload failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-40 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-neutral-800 rounded-lg shadow-xl w-full max-w-md" role="dialog" aria-modal="true" aria-labelledby="upload-title">
        <div className="flex items-center justify-between p-6 border-b border-neutral-200 dark:border-neutral-700">
          <h2 id="upload-title" className="text-lg font-semibold text-neutral-800 dark:text-neutral-100">Upload Document</h2>
          <button onClick={onClose} aria-label="Close" className="text-neutral-400 hover:text-neutral-600">✕</button>
        </div>
        <form onSubmit={submit}>
          <div className="p-6 space-y-4">
            {error && <div className="text-sm text-danger-600 bg-danger-50 border border-danger-200 rounded p-3" role="alert">{error}</div>}

            {/* Drop zone */}
            <div
              onDragOver={e => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onDrop={e => { e.preventDefault(); setDragging(false); if (e.dataTransfer.files[0]) pick(e.dataTransfer.files[0]) }}
              className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors
                ${dragging ? 'border-primary-500 bg-primary-50' : 'border-neutral-300 dark:border-neutral-600 hover:border-primary-400 hover:bg-primary-50 dark:hover:bg-primary-900/10'}`}
              onClick={() => document.getElementById('file-input')?.click()}
            >
              <input id="file-input" type="file" className="hidden"
                accept=".pdf,.docx,.txt,.md,.csv,.png,.jpg,.jpeg"
                onChange={e => e.target.files?.[0] && pick(e.target.files[0])} />
              {file ? (
                <div className="flex items-center justify-center gap-3">
                  <span className="text-2xl" aria-hidden="true">📄</span>
                  <div className="text-left">
                    <p className="text-sm font-medium text-neutral-800 dark:text-neutral-100">{file.name}</p>
                    <p className="text-xs text-neutral-400">{(file.size / 1024).toFixed(1)} KB</p>
                  </div>
                  <button type="button" onClick={e => { e.stopPropagation(); setFile(null) }}
                    className="ml-auto text-neutral-400 hover:text-danger-600" aria-label="Remove file">✕</button>
                </div>
              ) : (
                <div>
                  <p className="text-sm text-neutral-500">Drag &amp; drop or <span className="text-primary-600 font-medium">browse</span></p>
                  <p className="text-xs text-neutral-400 mt-1">PDF, DOCX, TXT, CSV, PNG, JPG · Max 50 MB</p>
                </div>
              )}
            </div>

            {/* OCR toggle */}
            <label className="flex items-center gap-3 cursor-pointer">
              <input type="checkbox" checked={runOcr} onChange={e => setRunOcr(e.target.checked)}
                className="h-4 w-4 rounded border-neutral-300 text-primary-600 focus:ring-primary-500" />
              <span className="text-sm text-neutral-700 dark:text-neutral-300">Run OCR (for scanned documents and images)</span>
            </label>
          </div>
          <div className="flex justify-end gap-3 p-6 border-t border-neutral-200 dark:border-neutral-700">
            <button type="button" onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-neutral-700 dark:text-neutral-300 border border-neutral-300 dark:border-neutral-600 rounded-md hover:bg-neutral-50">
              Cancel
            </button>
            <button type="submit" disabled={loading || !file}
              className="px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-md hover:bg-primary-700 disabled:opacity-50">
              {loading ? 'Uploading…' : 'Process Now'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------
// Source card
// ------------------------------------------------------------------
function SourceCard({ src, index }: { src: KBQuerySource; index: number }) {
  const [expanded, setExpanded] = useState(false)
  const pct = Math.round(src.score * 100)
  return (
    <div className="border border-neutral-200 dark:border-neutral-700 rounded-lg p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-neutral-800 dark:text-neutral-100 truncate">
            📄 {src.filename}{src.page_number ? ` · Page ${src.page_number}` : ''}
          </p>
          <div className="flex items-center gap-2 mt-1">
            <div className="flex-1 bg-neutral-200 dark:bg-neutral-700 rounded-full h-1.5">
              <div className="bg-primary-600 h-1.5 rounded-full" style={{ width: `${pct}%` }} />
            </div>
            <span className="text-xs text-neutral-500 flex-shrink-0">Relevance {pct}%</span>
          </div>
        </div>
        <span className="text-xs text-neutral-400 flex-shrink-0">[Source {index}]</span>
      </div>
      <div className={`mt-2 text-xs text-neutral-600 dark:text-neutral-400 ${expanded ? '' : 'line-clamp-2'}`}>
        {src.content}
      </div>
      <button onClick={() => setExpanded(p => !p)}
        className="text-xs text-primary-600 mt-1 hover:underline focus:outline-none">
        {expanded ? 'Show less' : 'Show more'}
      </button>
    </div>
  )
}

// ------------------------------------------------------------------
// Main page
// ------------------------------------------------------------------
export default function KnowledgeBaseDetailPage() {
  const { kbId } = useParams<{ kbId: string }>()
  const navigate = useNavigate()
  const { user } = useAuthStore()
  const { addToast } = useUIStore()

  const [kb, setKb] = useState<KBResponse | null>(null)
  const [docs, setDocs] = useState<DocumentResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [showUpload, setShowUpload] = useState(false)

  // Query state
  const [query, setQuery] = useState('')
  const [queryResult, setQueryResult] = useState<KBQueryResponse | null>(null)
  const [querying, setQuerying] = useState(false)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(async () => {
    if (!kbId) return
    try {
      const [kbData, docsData] = await Promise.all([kbApi.get(kbId), documentsApi.list(kbId)])
      setKb(kbData)
      setDocs(docsData)
    } catch {
      navigate('/knowledge-bases')
    } finally {
      setLoading(false)
    }
  }, [kbId])

  useEffect(() => {
    load()
    // Poll for status updates while any doc is processing
    pollingRef.current = setInterval(async () => {
      if (!kbId) return
      const d = await documentsApi.list(kbId).catch(() => [])
      setDocs(d)
      const stillProcessing = d.some(doc => doc.status === 'pending' || doc.status === 'processing')
      if (!stillProcessing && pollingRef.current) clearInterval(pollingRef.current)
    }, 4000)
    return () => { if (pollingRef.current) clearInterval(pollingRef.current) }
  }, [kbId])

  const handleDelete = async (docId: string, name: string) => {
    if (!window.confirm(`Delete "${name}"? This removes all indexed chunks. This cannot be undone.`)) return
    try {
      await documentsApi.delete(docId)
      setDocs(prev => prev.filter(d => d.id !== docId))
      if (kb) setKb({ ...kb, doc_count: Math.max(0, kb.doc_count - 1) })
      addToast({ type: 'success', title: 'Document deleted' })
    } catch {
      addToast({ type: 'error', title: 'Delete failed' })
    }
  }

  const handleQuery = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!query.trim() || !kbId) return
    setQuerying(true)
    setQueryResult(null)
    try {
      const result = await kbApi.query(kbId, { query, top_k: 5, generate_answer: true })
      setQueryResult(result)
    } catch (err: any) {
      addToast({ type: 'error', title: 'Query failed', message: err?.response?.data?.error?.message })
    } finally {
      setQuerying(false)
    }
  }

  const canUpload = user?.role === 'analyst' || user?.role === 'admin'

  if (loading) {
    return <div className="flex items-center justify-center min-h-64"><div className="animate-spin h-8 w-8 border-2 border-primary-600 border-t-transparent rounded-full" /></div>
  }
  if (!kb) return null

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <nav className="text-xs text-neutral-400 mb-1">
            <button onClick={() => navigate('/knowledge-bases')} className="hover:text-primary-600">Knowledge Bases</button>
            <span className="mx-1">/</span>
            <span className="text-neutral-600 dark:text-neutral-300">{kb.name}</span>
          </nav>
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">{kb.name}</h1>
          {kb.description && <p className="text-sm text-neutral-500 mt-1">{kb.description}</p>}
          <div className="flex gap-4 mt-2 text-xs text-neutral-500">
            <span><strong>{kb.doc_count}</strong> documents</span>
            <span><strong>{kb.chunk_count}</strong> chunks indexed</span>
            <span>Model: <code className="font-mono">{kb.embedding_model}</code></span>
          </div>
        </div>
        {canUpload && (
          <button onClick={() => setShowUpload(true)}
            className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700">
            📄 Upload Document
          </button>
        )}
      </div>

      {/* Local processing banner */}
      <div className="flex items-center gap-2 text-xs text-success-700 bg-success-50 border border-success-200 rounded-lg px-3 py-2 w-fit">
        <span aria-hidden="true">🔒</span>
        All processing is local — embeddings generated by Ollama, vectors stored in local Qdrant
      </div>

      {/* RAG Query */}
      <div className="bg-white dark:bg-neutral-800 rounded-lg shadow-sm border border-neutral-200 dark:border-neutral-700 p-6">
        <h2 className="text-base font-semibold text-neutral-800 dark:text-neutral-100 mb-4">Ask a Question</h2>
        <form onSubmit={handleQuery} className="flex gap-3">
          <input
            type="text" value={query} onChange={e => setQuery(e.target.value)}
            placeholder="Ask a question about your documents…"
            disabled={querying}
            className="flex-1 rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 placeholder-neutral-400 focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50"
          />
          <button type="submit" disabled={querying || !query.trim()}
            className="px-4 py-2 bg-primary-600 text-white rounded-md text-sm font-medium hover:bg-primary-700 disabled:opacity-50 flex-shrink-0">
            {querying ? <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full inline-block" aria-hidden="true" /> : 'Ask'}
          </button>
        </form>

        {queryResult && (
          <div className="mt-6 space-y-4">
            {queryResult.error && (
              <div className="p-3 bg-danger-50 border border-danger-200 rounded text-sm text-danger-700" role="alert">
                {queryResult.error}
              </div>
            )}

            {queryResult.answer && (
              <div className="p-4 bg-neutral-50 dark:bg-neutral-700 rounded-lg">
                <h3 className="text-xs font-semibold text-neutral-500 dark:text-neutral-400 uppercase tracking-wider mb-2">Answer</h3>
                <p className="text-sm text-neutral-800 dark:text-neutral-100 whitespace-pre-wrap">{queryResult.answer}</p>
              </div>
            )}

            {!queryResult.answer && !queryResult.error && (
              <p className="text-sm text-neutral-500 italic">No answer generated — try enabling answer generation or check if documents are indexed.</p>
            )}

            {queryResult.low_confidence && queryResult.sources.length === 0 && (
              <p className="text-sm text-warning-700 bg-warning-50 border border-warning-200 rounded p-3">
                No relevant information found. Try rephrasing your question or uploading relevant documents.
              </p>
            )}

            {queryResult.sources.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold text-neutral-500 dark:text-neutral-400 uppercase tracking-wider mb-2">
                  Sources ({queryResult.sources.length})
                  {queryResult.low_confidence && <span className="ml-2 text-warning-600 normal-case font-normal">· Low confidence</span>}
                </h3>
                <div className="space-y-3">
                  {queryResult.sources.map((src, i) => <SourceCard key={src.chunk_id} src={src} index={i + 1} />)}
                </div>
              </div>
            )}

            <div className="flex gap-4 text-xs text-neutral-400">
              <span>Embed: {queryResult.query_embedding_ms}ms</span>
              <span>Retrieve: {queryResult.retrieval_ms}ms</span>
              {queryResult.generation_ms != null && <span>Generate: {queryResult.generation_ms}ms</span>}
            </div>
          </div>
        )}
      </div>

      {/* Documents */}
      <div className="bg-white dark:bg-neutral-800 rounded-lg shadow-sm border border-neutral-200 dark:border-neutral-700">
        <div className="flex items-center justify-between px-6 py-4 border-b border-neutral-200 dark:border-neutral-700">
          <h2 className="text-base font-semibold text-neutral-800 dark:text-neutral-100">Documents</h2>
          <span className="text-xs text-neutral-500">{docs.length} file{docs.length !== 1 ? 's' : ''}</span>
        </div>

        {docs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <div className="text-3xl mb-2" aria-hidden="true">📄</div>
            <p className="text-sm text-neutral-500">No documents yet</p>
            {canUpload && <button onClick={() => setShowUpload(true)} className="mt-3 text-sm text-primary-600 hover:underline">Upload your first document</button>}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-neutral-50 dark:bg-neutral-700 text-left">
                <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider">Name</th>
                <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider">Status</th>
                <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider">Chunks</th>
                <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider">Size</th>
                <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider">Uploaded</th>
                {canUpload && <th className="px-4 py-3 text-xs font-medium text-neutral-500 uppercase tracking-wider sr-only">Actions</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-200 dark:divide-neutral-700">
              {docs.map(doc => (
                <tr key={doc.id} className="hover:bg-neutral-50 dark:hover:bg-neutral-700/50 transition-colors">
                  <td className="px-4 py-3">
                    <span className="font-medium text-neutral-800 dark:text-neutral-100 truncate max-w-xs block">{doc.original_name}</span>
                    {doc.error_message && <span className="text-xs text-danger-600 block truncate max-w-xs">{doc.error_message}</span>}
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={doc.status} /></td>
                  <td className="px-4 py-3 text-neutral-600 dark:text-neutral-400">{doc.chunk_count > 0 ? doc.chunk_count : '—'}</td>
                  <td className="px-4 py-3 text-neutral-500 text-xs">{(doc.size_bytes / 1024).toFixed(1)} KB</td>
                  <td className="px-4 py-3 text-neutral-500 text-xs">{formatISTDate(doc.created_at)}</td>
                  {canUpload && (
                    <td className="px-4 py-3">
                      <button onClick={() => handleDelete(doc.id, doc.original_name)}
                        className="text-neutral-400 hover:text-danger-600 text-sm transition-colors"
                        aria-label={`Delete ${doc.original_name}`}>
                        🗑
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showUpload && kbId && (
        <UploadModal
          kbId={kbId}
          onClose={() => setShowUpload(false)}
          onUploaded={doc => {
            setDocs(prev => [doc, ...prev])
            if (kb) setKb({ ...kb, doc_count: kb.doc_count + 1 })
          }}
        />
      )}
    </div>
  )
}
