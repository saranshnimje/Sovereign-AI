import { useState } from 'react'
import { CitationSource } from '../../api/chat'

interface EvidencePanelProps {
  sources: CitationSource[]
  onSourceClick?: (source: CitationSource) => void
}

const typeIcon = (type: string) => {
  switch (type) {
    case 'document': return '📄'
    case 'sensor': return '📊'
    case 'vision': return '👁'
    default: return '📎'
  }
}

/**
 * Collapsible evidence panel showing all sources used in a response.
 * Displays source type, label, filename/sensor, score, and content preview.
 */
export default function EvidencePanel({ sources, onSourceClick }: EvidencePanelProps) {
  const [expanded, setExpanded] = useState(false)

  if (sources.length === 0) return null

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium
          text-neutral-600 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700/50 transition-colors"
      >
        <span className="flex items-center gap-2">
          <span>Evidence ({sources.length} source{sources.length !== 1 ? 's' : ''})</span>
          <span className="flex gap-1">
            {sources.some(s => s.source_type === 'document') && (
              <span className="text-[10px] px-1 py-0.5 rounded bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-300">
                {sources.filter(s => s.source_type === 'document').length} doc
              </span>
            )}
            {sources.some(s => s.source_type === 'sensor') && (
              <span className="text-[10px] px-1 py-0.5 rounded bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-300">
                {sources.filter(s => s.source_type === 'sensor').length} sensor
              </span>
            )}
            {sources.some(s => s.source_type === 'vision') && (
              <span className="text-[10px] px-1 py-0.5 rounded bg-violet-100 text-violet-600 dark:bg-violet-900/30 dark:text-violet-300">
                {sources.filter(s => s.source_type === 'vision').length} vision
              </span>
            )}
          </span>
        </span>
        <span className="text-neutral-400">{expanded ? '▾' : '▸'}</span>
      </button>

      {expanded && (
        <div className="border-t border-neutral-200 dark:border-neutral-700 divide-y divide-neutral-100 dark:divide-neutral-700/50 max-h-64 overflow-y-auto">
          {sources.map((src) => (
            <button
              key={src.index}
              onClick={() => onSourceClick?.(src)}
              className="w-full text-left px-3 py-2 hover:bg-neutral-100 dark:hover:bg-neutral-700/50 transition-colors"
            >
              <div className="flex items-center gap-2 mb-0.5">
                <span>{typeIcon(src.source_type)}</span>
                <span className="font-medium text-xs">{src.label}</span>
                {src.score != null && (
                  <span className="text-[10px] text-neutral-400">{(src.score * 100).toFixed(0)}% match</span>
                )}
              </div>
              <div className="text-[11px] text-neutral-500 truncate">
                {src.filename && <span>{src.filename}{src.page_number != null ? `, p.${src.page_number}` : ''}</span>}
                {src.sensor && <span className="font-mono">{src.sensor}{src.severity ? ` (${src.severity})` : ''}</span>}
              </div>
              {src.content_preview && (
                <p className="text-[10px] text-neutral-400 mt-0.5 line-clamp-2">{src.content_preview}</p>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
