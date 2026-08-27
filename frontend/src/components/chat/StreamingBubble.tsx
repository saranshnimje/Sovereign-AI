import { CitationSource } from '../../api/chat'
import MarkdownRenderer from './MarkdownRenderer'
import CitationChip from './CitationChip'

interface StreamingBubbleProps {
  content: string
  model: string
  sources?: CitationSource[]
  onStop?: () => void
  onCitationClick?: (source: CitationSource) => void
}

// Regex patterns for citation matching
const CITATION_REGEX = /\[Source (\d+)\]|\[Doc (\d+): ([^\]]+)\]/g

/**
 * Streaming assistant response bubble with:
 * - Live markdown rendering
 * - Citation chips (matched against evidence sources)
 * - Blinking cursor animation
 * - Stop button (when generating)
 */
export default function StreamingBubble({
  content, model, sources = [], onStop, onCitationClick,
}: StreamingBubbleProps) {
  // Parse citations in streaming content
  const renderContent = () => {
    if (!content || sources.length === 0) {
      return content
        ? <MarkdownRenderer content={content} />
        : <span className="streaming-cursor" />
    }

    const parts: (string | JSX.Element)[] = []
    let lastIndex = 0
    let match: RegExpExecArray | null

    const regex = new RegExp(CITATION_REGEX.source, 'g')
    while ((match = regex.exec(content)) !== null) {
      if (match.index > lastIndex) {
        parts.push(content.slice(lastIndex, match.index))
      }

      const sourceNum = match[1] ? parseInt(match[1], 10) : parseInt(match[2], 10)
      const source = sources.find(s => s.index === sourceNum)
      if (source) {
        parts.push(
          <CitationChip
            key={`stream-cite-${match.index}`}
            source={source}
            onClick={onCitationClick}
          />
        )
      } else {
        parts.push(match[0])
      }
      lastIndex = match.index + match[0].length
    }
    if (lastIndex < content.length) {
      parts.push(content.slice(lastIndex))
    }

    // Render markdown for text parts, interleave with chips
    const rendered: JSX.Element[] = []
    let textBuffer = ''
    for (const part of parts) {
      if (typeof part === 'string') {
        textBuffer += part
      } else {
        if (textBuffer) {
          rendered.push(<MarkdownRenderer key={`smd-${rendered.length}`} content={textBuffer} />)
          textBuffer = ''
        }
        rendered.push(part)
      }
    }
    if (textBuffer) {
      rendered.push(<MarkdownRenderer key={`smd-${rendered.length}`} content={textBuffer} />)
    }
    if (content) {
      rendered.push(<span key="cursor" className="streaming-cursor" />)
    }

    return <>{rendered}</>
  }

  return (
    <div className="flex justify-start mb-3">
      <div className="max-w-[80%] px-4 py-3 rounded-2xl rounded-tl-sm bg-white dark:bg-neutral-800
        border border-neutral-200 dark:border-neutral-700 text-sm text-neutral-800 dark:text-neutral-100">
        <div className="flex items-center justify-between gap-2 mb-1">
          <span className="text-xs text-neutral-400 flex items-center gap-1">
            <span aria-hidden="true">⚡</span> {model}
          </span>
          {onStop && (
            <button
              onClick={onStop}
              className="px-2 py-0.5 text-[10px] font-medium rounded bg-danger-100 text-danger-700
                hover:bg-danger-200 dark:bg-danger-900/30 dark:text-danger-300 transition-colors"
              aria-label="Stop generation"
            >
              ■ Stop
            </button>
          )}
        </div>
        {renderContent()}
      </div>
    </div>
  )
}
