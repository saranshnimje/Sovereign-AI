import { useEffect, useState, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { knowledgeBasesApi, Document, DocumentPreview } from '../../api/knowledgeBases'

interface Props {
  document: Document
  onClose: () => void
}

function getExt(filename: string) {
  const parts = filename.split('.')
  return parts.length > 1 ? parts.pop()!.toLowerCase() : ''
}

function kindFor(doc: Document) {
  const ext = getExt(doc.original_name)
  if (ext === 'md' || ext === 'markdown' || doc.mime_type === 'text/markdown') return 'markdown'
  if (ext === 'json' || doc.mime_type === 'application/json') return 'json'
  if (ext === 'csv' || doc.mime_type === 'text/csv') return 'csv'
  if (ext === 'pdf' || doc.mime_type === 'application/pdf') return 'pdf'
  if ((doc.mime_type || '').startsWith('image/')) return 'image'
  return 'text'
}

export default function DocumentPreviewSafeModal({ document: doc, onClose }: Props) {
  const [preview, setPreview] = useState<DocumentPreview | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const blobUrlRef = useRef<string | null>(null)

  useEffect(() => {
    return () => {
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current)
        blobUrlRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    if (doc.status === 'pending' || doc.status === 'processing') return
    let cancelled = false
    setLoading(true)
    setError(null)
    knowledgeBasesApi.previewDocument(doc.id)
      .then(data => { if (!cancelled) setPreview(data) })
      .catch(err => {
        if (!cancelled) {
          const detail = err?.response?.data?.detail
          setError(detail || 'The original file is not available on the server. Re-upload this document.')
        }
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [doc.id, doc.status])

  const download = async () => {
    try {
      const url = await knowledgeBasesApi.downloadDocument(doc.id, doc.original_name)
      const a = document.createElement('a')
      a.href = url
      a.download = doc.original_name
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch {
      setError('Download failed. Please try again.')
    }
  }

  const renderContent = () => {
    if (doc.status === 'pending' || doc.status === 'processing') {
      return (
        <div className="flex flex-col items-center justify-center h-64 text-neutral-400">
          <div className="animate-spin h-8 w-8 border-2 border-cyan-500 border-t-transparent rounded-full mb-4" />
          <p className="text-sm font-medium text-neutral-200">Document is still processing</p>
          <p className="text-xs text-neutral-500 mt-1">Preview will be available after indexing completes.</p>
        </div>
      )
    }
    if (loading) return <div className="flex items-center justify-center h-64"><div className="animate-spin h-8 w-8 border-2 border-cyan-500 border-t-transparent rounded-full" /></div>
    if (error) return (
      <div className="flex flex-col items-center justify-center h-64 text-neutral-400 text-center">
        <p className="text-sm text-red-400 mb-2">Preview unavailable</p>
        <p className="text-xs max-w-md">{error}</p>
        <button onClick={download} className="mt-4 px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm hover:bg-cyan-500">Try Download</button>
      </div>
    )
    if (!preview?.content) return <div className="text-sm text-neutral-500 text-center py-10">No preview content available.</div>

    const kind = kindFor(doc)
    if (kind === 'markdown') return <div className="prose-invert max-w-none p-5 bg-surface-overlay rounded-lg border border-surface-border overflow-auto max-h-[70vh]"><ReactMarkdown remarkPlugins={[remarkGfm]}>{preview.content}</ReactMarkdown></div>
    if (kind === 'json') {
      try { return <pre className="p-5 bg-surface-overlay rounded-lg border border-surface-border overflow-auto max-h-[70vh] text-sm font-mono text-neutral-300 whitespace-pre-wrap">{JSON.stringify(JSON.parse(preview.content), null, 2)}</pre> }
      catch { /* fall through */ }
    }
    return <pre className="p-5 bg-surface-overlay rounded-lg border border-surface-border overflow-auto max-h-[70vh] text-sm font-mono text-neutral-300 whitespace-pre-wrap">{preview.content}</pre>
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="bg-surface-raised border border-surface-border rounded-xl shadow-2xl w-full max-w-5xl max-h-[95vh] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-surface-border">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-white truncate">{doc.original_name}</p>
            <p className="text-[10px] text-neutral-500 mt-1">{doc.status} · {doc.chunk_count || 0} chunks</p>
          </div>
          <div className="flex items-center gap-2 ml-3">
            <button onClick={download} className="px-3 py-1.5 text-xs border border-surface-border rounded-lg text-neutral-300 hover:bg-surface-muted">Download</button>
            <button onClick={onClose} className="px-3 py-1.5 text-xs text-neutral-400 hover:text-white">Close</button>
          </div>
        </div>
        <div className="p-5 overflow-auto">{renderContent()}</div>
      </div>
    </div>
  )
}
