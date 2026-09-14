import { useEffect, useState, useCallback } from 'react'
import { artifactsApi, Artifact } from '../api/artifacts'
import { useUIStore } from '../stores/uiStore'
import Badge from '../components/ui/Badge'
import ArtifactPreviewModal from '../components/artifacts/ArtifactPreviewModal'

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

function formatDate(d: string | null): string {
  if (!d) return '—'
  return new Date(d).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function fileIcon(mime: string | null, filename: string): string {
  if (mime?.startsWith('image/')) return '🖼️'
  if (mime === 'application/pdf') return '📄'
  if (mime === 'text/csv' || filename.endsWith('.csv')) return '📊'
  if (mime === 'application/json' || filename.endsWith('.json')) return '🔧'
  if (mime?.startsWith('text/markdown') || filename.endsWith('.md')) return '📝'
  if (mime?.startsWith('text/') || filename.match(/\.(js|ts|py|rb|go|rs|java|c|cpp|sh|sql|yaml|yml|toml|xml|html|css)$/)) return '💻'
  return '📎'
}

export default function DataPage() {
  const { addToast } = useUIStore()
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [loading, setLoading] = useState(true)
  const [previewArtifact, setPreviewArtifact] = useState<Artifact | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await artifactsApi.listArtifacts()
      setArtifacts(data)
    } catch {
      addToast({ type: 'error', title: 'Failed to load artifacts' })
    }
    setLoading(false)
  }, [addToast])

  useEffect(() => { load() }, [load])

  const handleDelete = async (artifact: Artifact) => {
    if (!window.confirm(`Delete "${artifact.filename}"? This cannot be undone.`)) return
    setDeleting(artifact.id)
    try {
      await artifactsApi.deleteArtifact(artifact.id)
      setArtifacts(prev => prev.filter(a => a.id !== artifact.id))
      addToast({ type: 'info', title: 'Artifact deleted', message: artifact.filename })
    } catch {
      addToast({ type: 'error', title: 'Delete failed' })
    }
    setDeleting(null)
  }

  const handleDownload = async (artifact: Artifact) => {
    try {
      const url = await artifactsApi.downloadUrl(artifact.id)
      const a = document.createElement('a')
      a.href = url
      a.download = artifact.filename
      a.click()
    } catch {
      addToast({ type: 'error', title: 'Download failed' })
    }
  }

  const filtered = artifacts.filter(a =>
    !searchQuery || a.filename.toLowerCase().includes(searchQuery.toLowerCase()) || (a.mime_type ?? '').toLowerCase().includes(searchQuery.toLowerCase())
  )

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-lg md:text-2xl font-bold text-white">Artifacts</h1>
          <p className="text-xs md:text-sm text-neutral-400 mt-1">Browse, preview, and download agent-generated files.</p>
        </div>
        <button onClick={load} className="px-3 md:px-4 py-2 border border-surface-border text-neutral-300 rounded-lg text-sm font-medium hover:bg-surface-muted transition-colors">
          Refresh
        </button>
      </div>

      {/* Search */}
      <div className="relative max-w-md">
        <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-neutral-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        <input
          type="text"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          placeholder="Search artifacts..."
          className="w-full pl-9 pr-3 py-2 bg-surface-raised border border-surface-border rounded-lg text-sm text-neutral-200 placeholder:text-neutral-500 focus:outline-none focus:ring-2 focus:ring-cyan-500"
        />
      </div>

      {/* Stats bar */}
      {!loading && artifacts.length > 0 && (
        <div className="flex items-center gap-4 text-[11px] text-neutral-500">
          <span>{artifacts.length} artifact{artifacts.length !== 1 ? 's' : ''}</span>
          <span>·</span>
          <span>{formatBytes(artifacts.reduce((sum, a) => sum + a.size_bytes, 0))} total</span>
          {searchQuery && <span className="text-cyan-500">({filtered.length} matching)</span>}
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => <div key={i} className="skeleton h-20" />)}
        </div>
      ) : artifacts.length === 0 ? (
        <div className="bg-surface-raised border border-surface-border rounded-xl p-12 text-center">
          <div className="w-16 h-16 rounded-2xl bg-cyan-500/10 flex items-center justify-center text-3xl mx-auto mb-4">
            <svg className="w-8 h-8 text-cyan-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m6.75 12H9.75m-3.75 3H6.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V18.75m-7.5-12h.008v.008H9.75V9.75zm0 3h.008v.008H9.75V12.75zm0 3h.008v.008H9.75v-.008z" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-white mb-2">No Artifacts</h3>
          <p className="text-sm text-neutral-400">Agent-generated files will appear here as they are created.</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="bg-surface-raised border border-surface-border rounded-xl p-8 text-center">
          <p className="text-sm text-neutral-400">No artifacts match "{searchQuery}"</p>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map(artifact => (
            <div
              key={artifact.id}
              className="bg-surface-raised border border-surface-border rounded-xl p-4 hover:border-cyan-700/50 transition-all"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3 min-w-0 flex-1">
                  <span className="text-xl flex-shrink-0">{fileIcon(artifact.mime_type, artifact.filename)}</span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-neutral-200 truncate">{artifact.filename}</p>
                    <div className="flex items-center gap-2 text-[10px] text-neutral-500 mt-0.5">
                      <span>{formatBytes(artifact.size_bytes)}</span>
                      <span>·</span>
                      <span>{artifact.mime_type || 'unknown type'}</span>
                      <span>·</span>
                      <span>{formatDate(artifact.created_at)}</span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <button
                    onClick={() => setPreviewArtifact(artifact)}
                    className="px-3 py-1.5 text-xs bg-cyan-600 text-white rounded-lg hover:bg-cyan-500 transition-colors"
                  >
                    Preview
                  </button>
                  <button
                    onClick={() => handleDownload(artifact)}
                    className="px-3 py-1.5 text-xs border border-surface-border text-neutral-300 rounded-lg hover:bg-surface-muted transition-colors"
                  >
                    Download
                  </button>
                  <button
                    onClick={() => handleDelete(artifact)}
                    disabled={deleting === artifact.id}
                    className="px-3 py-1.5 text-xs border border-danger-500/30 text-danger-500 rounded-lg hover:bg-danger-500/10 transition-colors disabled:opacity-50"
                  >
                    {deleting === artifact.id ? '...' : 'Delete'}
                  </button>
                </div>
              </div>
              {artifact.conversation_id && (
                <div className="mt-2 flex items-center gap-2">
                  <Badge variant="info" size="sm">conversation</Badge>
                  <span className="text-[10px] text-neutral-500 font-mono truncate">{artifact.conversation_id}</span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Preview Modal */}
      {previewArtifact && (
        <ArtifactPreviewModal
          artifact={previewArtifact}
          onClose={() => setPreviewArtifact(null)}
        />
      )}
    </div>
  )
}
