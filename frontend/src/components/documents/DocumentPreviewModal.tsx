import { useEffect, useState, useRef, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { knowledgeBasesApi, Document, DocumentPreview } from '../../api/knowledgeBases'
import PDFViewer from './PDFViewer'
import DocxViewer from './DocxViewer'

interface Props {
  document: Document
  onClose: () => void
}

type PreviewKind = 'pdf' | 'docx' | 'image' | 'text' | 'markdown' | 'json' | 'csv' | 'code'

const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp', 'ico']
const CODE_EXTS = ['js', 'ts', 'tsx', 'jsx', 'py', 'rb', 'go', 'rs', 'java', 'c', 'cpp', 'h', 'hpp', 'cs', 'php', 'sh', 'bash', 'zsh', 'sql', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf', 'xml', 'html', 'css', 'scss', 'less']

function getExt(filename: string): string {
  const parts = filename.split('.')
  return parts.length > 1 ? parts.pop()!.toLowerCase() : ''
}

function detectKind(filename: string, mime: string | null): PreviewKind {
  const ext = getExt(filename)
  if (ext === 'pdf' || mime === 'application/pdf') return 'pdf'
  if (ext === 'docx' || mime === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') return 'docx'
  if (IMAGE_EXTS.includes(ext) || (mime ?? '').startsWith('image/')) return 'image'
  if (ext === 'md' || ext === 'markdown' || mime === 'text/markdown') return 'markdown'
  if (ext === 'json' || mime === 'application/json') return 'json'
  if (ext === 'csv' || mime === 'text/csv') return 'csv'
  if (CODE_EXTS.includes(ext)) return 'code'
  return 'text'
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

function parseCsvLine(line: string): string[] {
  const result: string[] = []
  let current = ''
  let inQuotes = false
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]
    if (inQuotes) {
      if (ch === '"') {
        if (i + 1 < line.length && line[i + 1] === '"') { current += '"'; i++ }
        else inQuotes = false
      } else current += ch
    } else {
      if (ch === '"') inQuotes = true
      else if (ch === ',') { result.push(current); current = '' }
      else current += ch
    }
  }
  result.push(current)
  return result
}

function getErrorMessage(err: unknown): string {
  if (err && typeof err === 'object' && 'response' in err) {
    const axiosErr = err as { response?: { status?: number; data?: unknown } }
    if (axiosErr.response?.status === 404) return 'Document not found on server. It may have been deleted.'
    if (axiosErr.response?.status === 403) return 'You do not have permission to view this document.'
    if (axiosErr.response?.status === 429) return 'Too many requests. Please wait a moment and try again.'
    if (axiosErr.response?.status === 500) return 'Server error. Please try again later.'
    const detail = (axiosErr.response?.data as { detail?: string })?.detail
    if (detail) return detail
    return `Request failed (HTTP ${axiosErr.response?.status || 'unknown'})`
  }
  if (err instanceof TypeError && err.message.includes('Failed to fetch')) {
    return 'Network error. Please check your connection.'
  }
  return 'Failed to load document preview'
}

export default function DocumentPreviewModal({ document: doc, onClose }: Props) {
  const [preview, setPreview] = useState<DocumentPreview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [zoom, setZoom] = useState(1)
  const [previewBlobUrl, setPreviewBlobUrl] = useState<string | null>(null)
  const [docxBuffer, setDocxBuffer] = useState<ArrayBuffer | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const overlayRef = useRef<HTMLDivElement>(null)
  const blobUrlsRef = useRef<string[]>([])

  const kind = detectKind(doc.original_name, doc.mime_type)

  useEffect(() => {
    return () => {
      blobUrlsRef.current.forEach(url => URL.revokeObjectURL(url))
      blobUrlsRef.current = []
    }
  }, [])

  const loadContent = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      if (kind === 'pdf' || kind === 'image') {
        const blobUrl = await knowledgeBasesApi.getPreviewBlobUrl(doc.id)
        blobUrlsRef.current.push(blobUrl)
        setPreviewBlobUrl(blobUrl)
        setPreview({ content: null, filename: doc.original_name, mime_type: doc.mime_type, truncated: false, binary: true })
      } else if (kind === 'docx') {
        const buffer = await knowledgeBasesApi.getDocumentBlob(doc.id)
        setDocxBuffer(buffer)
        setPreview({ content: null, filename: doc.original_name, mime_type: doc.mime_type, truncated: false, binary: true })
      } else {
        const data = await knowledgeBasesApi.previewDocument(doc.id)
        setPreview(data)
      }
    } catch (err) {
      console.error(`[DocumentPreview] Failed to load ${kind} preview for doc ${doc.id}:`, err)
      setError(getErrorMessage(err))
    }
    setLoading(false)
  }, [doc.id, doc.original_name, doc.mime_type, kind])

  useEffect(() => { loadContent() }, [loadContent])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current) onClose()
  }

  const handleDownload = async () => {
    try {
      const url = await knowledgeBasesApi.downloadDocument(doc.id, doc.original_name)
      const a = document.createElement('a')
      a.href = url
      a.download = doc.original_name
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) {
      console.error('[DocumentPreview] Download failed:', err)
      setError(getErrorMessage(err))
    }
  }

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      overlayRef.current?.requestFullscreen()
      setFullscreen(true)
    } else {
      document.exitFullscreen()
      setFullscreen(false)
    }
  }

  useEffect(() => {
    const handler = () => setFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', handler)
    return () => document.removeEventListener('fullscreenchange', handler)
  }, [])

  const zoomIn = () => setZoom(z => Math.min(z + 0.25, 3))
  const zoomOut = () => setZoom(z => Math.max(z - 0.25, 0.25))
  const zoomReset = () => setZoom(1)

  const kindLabel = kind === 'pdf' ? 'PDF' : kind === 'docx' ? 'DOCX' : kind.toUpperCase()

  const renderContent = () => {
    if (loading) {
      return (
        <div className="flex flex-col items-center justify-center h-96 gap-3">
          <div className="animate-spin h-8 w-8 border-2 border-cyan-500 border-t-transparent rounded-full" />
          <p className="text-sm text-neutral-400">Loading document preview...</p>
        </div>
      )
    }

    if (error) {
      return (
        <div className="flex flex-col items-center justify-center h-96 text-neutral-400">
          <svg className="w-12 h-12 mb-3 text-neutral-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
          <p className="text-sm mb-1">{error}</p>
          <p className="text-xs text-neutral-500 mb-4">Preview unavailable for this document. You can download the original file instead.</p>
          <button onClick={handleDownload} className="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm hover:bg-cyan-500 transition-colors">
            Download Instead
          </button>
        </div>
      )
    }

    switch (kind) {
      case 'pdf':
        if (!previewBlobUrl) return <div className="flex items-center justify-center h-96 text-neutral-400">Loading PDF...</div>
        return <PDFViewer url={previewBlobUrl} filename={doc.original_name} />

      case 'docx':
        if (!docxBuffer) return <div className="flex items-center justify-center h-96 text-neutral-400">Loading document...</div>
        return <DocxViewer arrayBuffer={docxBuffer} filename={doc.original_name} />

      case 'image':
        return (
          <div className="flex flex-col items-center gap-3 h-full">
            <div className="flex gap-2">
              <button onClick={zoomOut} className="px-2 py-1 text-xs bg-surface-overlay border border-surface-border rounded text-neutral-400 hover:text-neutral-200 transition-colors">{'\u2212'}</button>
              <button onClick={zoomReset} className="px-2 py-1 text-xs bg-surface-overlay border border-surface-border rounded text-neutral-400 hover:text-neutral-200 transition-colors">{Math.round(zoom * 100)}%</button>
              <button onClick={zoomIn} className="px-2 py-1 text-xs bg-surface-overlay border border-surface-border rounded text-neutral-400 hover:text-neutral-200 transition-colors">+</button>
            </div>
            <div className="flex-1 overflow-auto rounded-lg bg-neutral-900 p-4 flex items-center justify-center">
              {previewBlobUrl ? (
                <img src={previewBlobUrl} alt={doc.original_name}
                  style={{ transform: `scale(${zoom})`, transformOrigin: 'top left' }}
                  className="max-w-none transition-transform" />
              ) : (
                <div className="text-neutral-400 text-sm">Loading image...</div>
              )}
            </div>
          </div>
        )

      case 'markdown':
        return (
          <div className="flex-1 overflow-auto p-6">
            <div className="prose-invert max-w-3xl mx-auto prose prose-sm prose-headings:text-white prose-p:text-neutral-300 prose-a:text-cyan-400">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{preview?.content ?? ''}</ReactMarkdown>
            </div>
          </div>
        )

      case 'json':
        try {
          const parsed = JSON.parse(preview?.content ?? '{}')
          return (
            <pre className="p-6 font-mono text-sm text-neutral-300 whitespace-pre-wrap overflow-auto max-h-[70vh] bg-surface-overlay rounded-lg m-4 border border-surface-border">
              {JSON.stringify(parsed, null, 2)}
            </pre>
          )
        } catch {
          return <pre className="p-6 font-mono text-sm text-neutral-300 whitespace-pre-wrap overflow-auto max-h-[70vh]">{preview?.content}</pre>
        }

      case 'csv': {
        const lines = (preview?.content ?? '').split(/\r?\n/).filter(l => l.trim())
        if (lines.length === 0) return <p className="text-neutral-500 text-sm text-center py-8">Empty CSV file</p>
        const rows = lines.map(parseCsvLine)
        const headers = rows[0]
        const body = rows.slice(1)
        return (
          <div className="overflow-auto max-h-[70vh] m-4 rounded-lg border border-surface-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-surface-overlay border-b border-surface-border">
                  {headers.map((h, i) => (
                    <th key={i} className="px-3 py-2 text-left text-xs font-medium text-cyan-400 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {body.map((row, ri) => (
                  <tr key={ri} className="border-b border-surface-border/50 hover:bg-surface-muted/50">
                    {row.map((cell, ci) => (
                      <td key={ci} className="px-3 py-1.5 text-xs text-neutral-300 whitespace-nowrap">{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      }

      case 'code':
      case 'text':
      default:
        return (
          <pre className="p-6 font-mono text-sm text-neutral-300 leading-relaxed whitespace-pre-wrap overflow-auto max-h-[70vh]">
            {preview?.content}
          </pre>
        )
    }
  }

  return (
    <div
      ref={overlayRef}
      onClick={handleOverlayClick}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
    >
      <div className={`bg-surface-raised border border-surface-border rounded-xl shadow-2xl flex flex-col overflow-hidden ${fullscreen ? 'w-full h-full' : 'w-full max-w-6xl max-h-[95vh]'}`}>
        <div className="flex items-center justify-between px-5 py-3 border-b border-surface-border flex-shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-8 h-8 rounded-lg bg-cyan-500/10 flex items-center justify-center flex-shrink-0">
              {kind === 'pdf' ? (
                <svg className="w-4 h-4 text-red-400" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/>
                  <polyline points="14 2 14 8 20 8" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                  <text x="12" y="17" textAnchor="middle" fontSize="7" fontWeight="bold" fill="currentColor">PDF</text>
                </svg>
              ) : kind === 'docx' ? (
                <svg className="w-4 h-4 text-blue-400" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/>
                  <polyline points="14 2 14 8 20 8" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                  <text x="12" y="17" textAnchor="middle" fontSize="6" fontWeight="bold" fill="currentColor">DOCX</text>
                </svg>
              ) : (
                <svg className="w-4 h-4 text-cyan-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                </svg>
              )}
            </div>
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-white truncate">{doc.original_name}</h2>
              <div className="flex items-center gap-2 text-[10px] text-neutral-500">
                <span className="px-1.5 py-0.5 rounded bg-surface-muted text-neutral-400 font-medium">{kindLabel}</span>
                {doc.size_bytes != null && <span>{formatBytes(doc.size_bytes)}</span>}
                {doc.page_count != null && doc.page_count > 0 && <span>{doc.page_count} pages</span>}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1.5 flex-shrink-0">
            <button onClick={toggleFullscreen} className="p-1.5 rounded-lg text-neutral-500 hover:bg-surface-muted hover:text-neutral-300 transition-colors" title={fullscreen ? 'Exit fullscreen' : 'Fullscreen'}>
              {fullscreen ? (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 9V4.5M9 9H4.5M9 9L3.75 3.75M9 15v4.5M9 15H4.5M9 15l-5.25 5.25M15 9h4.5M15 9V4.5M15 9l5.25-5.25M15 15h4.5M15 15v4.5m0-4.5l5.25 5.25" />
                </svg>
              ) : (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" />
                </svg>
              )}
            </button>
            <button onClick={handleDownload} className="px-3 py-1.5 text-xs bg-cyan-600 text-white rounded-lg hover:bg-cyan-500 transition-colors flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
              </svg>
              Download
            </button>
            <button onClick={onClose} className="p-1.5 rounded-lg text-neutral-500 hover:bg-surface-muted hover:text-neutral-300 transition-colors" aria-label="Close preview">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        <div className={`flex-1 overflow-hidden ${(kind === 'pdf' || kind === 'docx') ? '' : 'overflow-auto'}`}>
          {renderContent()}
        </div>
      </div>
    </div>
  )
}
