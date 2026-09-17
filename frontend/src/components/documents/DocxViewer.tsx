import { useEffect, useState, useRef } from 'react'
import mammoth from 'mammoth'

interface Props {
  arrayBuffer: ArrayBuffer
  filename: string
}

function sanitizeHtml(html: string): string {
  const div = document.createElement('div')
  div.innerHTML = html
  const scripts = div.querySelectorAll('script, iframe, object, embed, form')
  scripts.forEach(el => el.remove())
  div.querySelectorAll('*').forEach(el => {
    const attrs = Array.from(el.attributes)
    for (const attr of attrs) {
      if (attr.name.startsWith('on') || attr.value.trim().toLowerCase().startsWith('javascript:')) {
        el.removeAttribute(attr.name)
      }
    }
  })
  return div.innerHTML
}

export default function DocxViewer({ arrayBuffer, filename }: Props) {
  const [html, setHtml] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const contentRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    const convert = async () => {
      try {
        setLoading(true)
        setError(null)
        const result = await mammoth.convertToHtml({ arrayBuffer })
        if (cancelled) return
        setHtml(sanitizeHtml(result.value))
      } catch {
        if (!cancelled) setError('Failed to convert DOCX document')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    convert()
    return () => { cancelled = true }
  }, [arrayBuffer])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="flex flex-col items-center gap-3">
          <div className="animate-spin h-8 w-8 border-2 border-cyan-500 border-t-transparent rounded-full" />
          <p className="text-sm text-neutral-400">Converting document...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-96 text-neutral-400">
        <svg className="w-12 h-12 mb-3 text-neutral-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
        </svg>
        <p className="text-sm">{error}</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center px-4 py-2 bg-surface-overlay border-b border-surface-border flex-shrink-0">
        <div className="text-xs text-neutral-500 truncate">{filename}</div>
      </div>
      <div ref={contentRef} className="flex-1 overflow-auto p-6">
        <div
          className="docx-content max-w-3xl mx-auto prose prose-invert prose-sm
            prose-headings:text-white prose-p:text-neutral-300 prose-li:text-neutral-300
            prose-strong:text-neutral-200 prose-em:text-neutral-300
            prose-table:border-collapse prose-th:border prose-th:border-surface-border
            prose-th:px-3 prose-th:py-2 prose-th:text-left prose-th:text-xs prose-th:text-cyan-400
            prose-td:border prose-td:border-surface-border prose-td:px-3 prose-td:py-2 prose-td:text-xs prose-td:text-neutral-300
            prose-a:text-cyan-400 prose-code:text-cyan-300 prose-code:bg-surface-overlay prose-code:px-1 prose-code:py-0.5 prose-code:rounded
            prose-pre:bg-surface-overlay prose-pre:border prose-pre:border-surface-border"
          dangerouslySetInnerHTML={{ __html: html || '' }}
        />
      </div>
    </div>
  )
}
