import { useEffect, useState, useRef, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { knowledgeBasesApi, Document, DocumentPreview } from '../../api/knowledgeBases'

interface DocumentPreviewModalProps {
  document: Document
  onClose: () => void
}

type PreviewKind = 'pdf' | 'image' | 'text' | 'markdown' | 'json' | 'csv' | 'code' | 'binary'

const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp', 'ico']
const CODE_EXTS = ['js', 'ts', 'tsx', 'jsx', 'py', 'rb', 'go', 'rs', 'java', 'c', 'cpp', 'h', 'hpp', 'cs', 'php', 'sh', 'bash', 'zsh', 'sql', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf', 'xml', 'html', 'css', 'scss', 'less']

function getExt(filename: string): string {
  const parts = filename.split('.')
  return parts.length > 1 ? parts.pop()!.toLowerCase() : ''
}

function detectKind(filename: string, mime: string | null): PreviewKind {
  const ext = getExt(filename)
  if (ext === 'pdf' || mime === 'application/pdf') return 'pdf'
  if (IMAGE_EXTS.includes(ext) || (mime ?? '').startsWith('image/')) return 'image'
  if (ext === 'md' || ext === 'markdown' || mime === 'text/markdown') return 'markdown'
  if (ext === 'json' || mime === 'application/json') return 'json'
  if (ext === 'csv' || mime === 'text/csv') return 'csv'
  if (CODE_EXTS.includes(ext)) return 'code'
  if (['txt', 'log', 'rtf', 'ini', 'cfg', 'conf'].includes(ext) || (mime ?? '').startsWith('text/')) return 'text'
  return 'binary'
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

function formatDate(d: string | null): string {
  if (!d) return '\u2014'
  return new Date(d).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function highlightJson(obj: unknown, indent = 0): string {
  const pad = '  '.repeat(indent)
  const pad1 = '  '.repeat(indent + 1)
  if (obj === null) return '<span class="text-neutral-500">null</span>'
  if (obj === undefined) return '<span class="text-neutral-500">undefined</span>'
  if (typeof obj === 'string') return `<span class="text-green-400">"${obj.replace(/</g, '&lt;').replace(/>/g, '&gt;')}"</span>`
  if (typeof obj === 'number') return `<span class="text-cyan-400">${obj}</span>`
  if (typeof obj === 'boolean') return `<span class="text-amber-400">${obj}</span>`
  if (Array.isArray(obj)) {
    if (obj.length === 0) return '[]'
    const items = obj.map(v => `${pad1}${highlightJson(v, indent + 1)}`)
    return `[\n${items.join(',\n')}\n${pad}]`
  }
  if (typeof obj === 'object') {
    const keys = Object.keys(obj as Record<string, unknown>)
    if (keys.length === 0) return '{}'
    const entries = keys.map(k => {
      const val = highlightJson((obj as Record<string, unknown>)[k], indent + 1)
      return `${pad1}<span class="text-blue-300">"${k.replace(/</g, '&lt;').replace(/>/g, '&gt;')}"</span>: ${val}`
    })
    return `{\n${entries.join(',\n')}\n${pad}}`
  }
  return String(obj)
}

function parseCsvLine(line: string): string[] {
  const result: string[] = []
  let current = ''
  let inQuotes = false
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]
    if (inQuotes) {
      if (ch === '"') {
        if (i + 1 < line.length && line[i + 1] === '"') {
          current += '"'
          i++
        } else {
          inQuotes = false
        }
      } else {
        current += ch
      }
    } else {
      if (ch === '"') {
        inQuotes = true
      } else if (ch === ',') {
        result.push(current)
        current = ''
      } else {
        current += ch
      }
    }
  }
  result.push(current)
  return result
}

function parseCsv(content: string): string[][] {
  const lines = content.split(/\r?\n/).filter(l => l.trim())
  return lines.map(parseCsvLine)
}

export default function DocumentPreviewModal({ document: doc, onClose }: DocumentPreviewModalProps) {
  const [preview, setPreview] = useState<DocumentPreview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [zoom, setZoom] = useState(1)
  const [previewBlobUrl, setPreviewBlobUrl] = useState<string | null>(null)
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
      } else {
        const data = await knowledgeBasesApi.previewDocument(doc.id)
        setPreview(data)
      }
    } catch {
      setError('Failed to load preview')
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
    } catch {
      setError('Download failed. Please try again.')
    }
  }

  const zoomIn = () => setZoom(z => Math.min(z + 0.25, 3))
  const zoomOut = () => setZoom(z => Math.max(z - 0.25, 0.25))
  const zoomReset = () => setZoom(1)

  const renderPreview = () => {
    if (loading) {
      return (
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin h-8 w-8 border-2 border-cyan-500 border-t-transparent rounded-full" />
        </div>
      )
    }

    if (error) {
      return (
        <div className="flex flex-col items-center justify-center h-64 text-neutral-400">
          <svg className="w-12 h-12 mb-3 text-neutral-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
          <p className="text-sm">{error}</p>
          <button onClick={handleDownload} className="mt-3 px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm hover:bg-cyan-500">
            Download Instead
          </button>
        </div>
      )
    }

    switch (kind) {
      case 'pdf':
        return (
          <div className="w-full h-[80vh]">
            {previewBlobUrl ? (
              <iframe
                src={`${previewBlobUrl}#toolbar=1`}
                className="w-full h-full rounded-lg border border-surface-border"
                title={doc.original_name}
              />
            ) : (
              <div className="flex items-center justify-center h-full text-neutral-400">Loading PDF...</div>
            )}
          </div>
        )

      case 'image':
        return (
          <div className="flex flex-col items-center gap-3">
            <div className="flex gap-2 mb-2">
              <button onClick={zoomOut} className="px-2 py-1 text-xs bg-surface-overlay border border-surface-border rounded text-neutral-400 hover:text-neutral-200">\u2212</button>
              <button onClick={zoomReset} className="px-2 py-1 text-xs bg-surface-overlay border border-surface-border rounded text-neutral-400 hover:text-neutral-200">{Math.round(zoom * 100)}%</button>
              <button onClick={zoomIn} className="px-2 py-1 text-xs bg-surface-overlay border border-surface-border rounded text-neutral-400 hover:text-neutral-200">+</button>
            </div>
            <div className="overflow-auto max-h-[75vh] rounded-lg border border-surface-border bg-surface p-2">
              {previewBlobUrl ? (
                <img
                  src={previewBlobUrl}
                  alt={doc.original_name}
                  style={{ transform: `scale(${zoom})`, transformOrigin: 'top left' }}
                  className="max-w-none transition-transform"
                />
              ) : (
                <div className="text-neutral-400 text-sm">Loading image...</div>
              )}
            </div>
          </div>
        )

      case 'markdown':
        return (
          <div className="prose-invert max-w-none p-4 bg-surface-overlay rounded-lg border border-surface-border overflow-auto max-h-[80vh]">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{preview?.content ?? ''}</ReactMarkdown>
          </div>
        )

      case 'json':
        try {
          const parsed = JSON.parse(preview?.content ?? '{}')
          const highlighted = highlightJson(parsed)
          return (
            <pre className="p-4 bg-surface-overlay rounded-lg border border-surface-border overflow-auto max-h-[80vh] text-sm font-mono leading-relaxed whitespace-pre-wrap">
              <code dangerouslySetInnerHTML={{ __html: highlighted }} />
            </pre>
          )
        } catch {
          return (
            <pre className="p-4 bg-surface-overlay rounded-lg border border-surface-border overflow-auto max-h-[80vh] text-sm font-mono text-neutral-300 whitespace-pre-wrap">
              {preview?.content}
            </pre>
          )
        }

      case 'csv': {
        const rows = parseCsv(preview?.content ?? '')
        if (rows.length === 0) return <p className="text-neutral-500 text-sm text-center py-8">Empty CSV file</p>
        const headers = rows[0]
        const body = rows.slice(1)
        return (
          <div className="overflow-auto max-h-[80vh] rounded-lg border border-surface-border">
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
        return (
          <pre className="p-4 bg-surface-overlay rounded-lg border border-surface-border overflow-auto max-h-[80vh] text-sm font-mono text-neutral-300 leading-relaxed whitespace-pre-wrap">
            {preview?.content}
          </pre>
        )

      case 'text':
        return (
          <pre className="p-4 bg-surface-overlay rounded-lg border border-surface-border overflow-auto max-h-[80vh] text-sm text-neutral-300 leading-relaxed whitespace-pre-wrap">
            {preview?.content}
          </pre>
        )

      case 'binary':
      default:
        return (
          <div className="flex flex-col items-center justify-center h-64 text-neutral-400">
            <svg className="w-16 h-16 mb-4 text-neutral-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
            </svg>
            <p className="text-sm font-medium text-neutral-300 mb-1">Preview not available for this file type</p>
            <p className="text-xs text-neutral-500 mb-4">Download to view locally</p>
            <button onClick={handleDownload} className="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm hover:bg-cyan-500">
              Download File
            </button>
          </div>
        )
    }
  }

  return (
    <div
      ref={overlayRef}
      onClick={handleOverlayClick}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
    >
      <div className="bg-surface-raised border border-surface-border rounded-xl shadow-2xl w-full max-w-5xl max-h-[95vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-surface-border flex-shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-8 h-8 rounded-lg bg-cyan-500/10 flex items-center justify-center text-cyan-400 flex-shrink-0">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
              </svg>
            </div>
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-white truncate">{doc.original_name}</h2>
              <div className="flex items-center gap-2 text-[10px] text-neutral-500">
                {doc.size_bytes != null && <span>{formatBytes(doc.size_bytes)}</span>}
                {doc.size_bytes != null && <span>\u00b7</span>}
                <span>{doc.mime_type || 'unknown'}</span>
                <span>\u00b7</span>
                <span>{formatDate(doc.created_at)}</span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              onClick={handleDownload}
              className="px-3 py-1.5 text-xs bg-cyan-600 text-white rounded-lg hover:bg-cyan-500 transition-colors"
            >
              Download
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-neutral-500 hover:bg-surface-muted hover:text-neutral-300 transition-colors"
              aria-label="Close preview"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto p-4">
          {renderPreview()}
        </div>
      </div>
    </div>
  )
}
