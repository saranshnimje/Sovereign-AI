import { useState } from 'react'

export interface CitationSource {
  index: number
  source_type: string
  label: string
  doc_id?: string
  filename?: string
  page_number?: number | null
  score?: number
  content_preview?: string
  analysis_id?: string
  sensor?: string
  severity?: string
}

interface CitationChipProps {
  source: CitationSource
  onClick?: (source: CitationSource) => void
}

/**
 * Clickable citation chip rendered inline in assistant messages.
 * Shows source label, type badge, and optional preview on hover.
 */
export default function CitationChip({ source, onClick }: CitationChipProps) {
  const [showPreview, setShowPreview] = useState(false)

  const typeBadge = (type: string) => {
    switch (type) {
      case 'document':
        return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
      case 'sensor':
        return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
      case 'vision':
        return 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300'
      default:
        return 'bg-neutral-100 text-neutral-600 dark:bg-neutral-700 dark:text-neutral-300'
    }
  }

  return (
    <span className="relative inline-block">
      <button
        onClick={(e) => {
          e.stopPropagation()
          onClick?.(source)
        }}
        onMouseEnter={() => setShowPreview(true)}
        onMouseLeave={() => setShowPreview(false)}
        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-medium
          border border-neutral-200 dark:border-neutral-600 cursor-pointer
          hover:shadow-sm transition-shadow ${typeBadge(source.source_type)}`}
        title={source.label}
      >
        <span>{source.label}</span>
        {source.score != null && (
          <span className="text-[9px] opacity-60">{(source.score * 100).toFixed(0)}%</span>
        )}
      </button>

      {/* Hover preview */}
      {showPreview && source.content_preview && (
        <div className="absolute z-30 bottom-full left-0 mb-1 w-72 p-2.5 bg-white dark:bg-neutral-800
          border border-neutral-200 dark:border-neutral-600 rounded-lg shadow-lg text-xs
          text-neutral-700 dark:text-neutral-200 pointer-events-none">
          <div className="flex items-center gap-2 mb-1.5">
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${typeBadge(source.source_type)}`}>
              {source.source_type}
            </span>
            {source.filename && (
              <span className="truncate text-neutral-500">{source.filename}</span>
            )}
            {source.page_number != null && (
              <span className="text-neutral-400">p.{source.page_number}</span>
            )}
            {source.sensor && (
              <span className="text-neutral-500 font-mono">{source.sensor}</span>
            )}
          </div>
          <p className="line-clamp-4 text-neutral-600 dark:text-neutral-300 leading-relaxed">
            {source.content_preview}
          </p>
          {source.severity && (
            <div className="mt-1 text-[10px] text-neutral-400">
              Severity: <span className="font-medium">{source.severity}</span>
            </div>
          )}
        </div>
      )}
    </span>
  )
}
