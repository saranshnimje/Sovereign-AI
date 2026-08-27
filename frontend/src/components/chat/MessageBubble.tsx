import { useMemo } from 'react'
import { MessageResponse, CitationSource } from '../../api/chat'
import MarkdownRenderer from './MarkdownRenderer'
import CitationChip from './CitationChip'

interface MessageBubbleProps {
  msg: MessageResponse
  onCitationClick?: (source: CitationSource) => void
}

// Regex patterns for citation matching
const SOURCE_NUM_PATTERN = /\[Source (\d+)\]/g
const DOC_LABEL_PATTERN = /\[Doc (\d+): ([^\]]+)\]/g

/**
 * Renders a chat message with markdown formatting and clickable citation chips.
 * User messages: plain text (right-aligned, primary color).
 * Assistant messages: markdown with citations (left-aligned, white card).
 */
export default function MessageBubble({ msg, onCitationClick }: MessageBubbleProps) {
  const isUser = msg.role === 'user'

  // Extract evidence sources from message metadata
  const sources: CitationSource[] = useMemo(() => {
    if (!msg.metadata?.evidence?.sources) return []
    return msg.metadata.evidence.sources as CitationSource[]
  }, [msg.metadata])

  // Parse citation references in content and render with chips
  const renderContent = () => {
    if (isUser || sources.length === 0) {
      return <MarkdownRenderer content={msg.content} />
    }

    // Split content by citation patterns and interleave with chips
    const parts: (string | JSX.Element)[] = []
    let lastIndex = 0
    let match: RegExpExecArray | null

    // Try Source N pattern first
    const combined = msg.content
    const regex = new RegExp(`${SOURCE_NUM_PATTERN.source}|${DOC_LABEL_PATTERN.source}`, 'g')

    while ((match = regex.exec(combined)) !== null) {
      // Add text before this match
      if (match.index > lastIndex) {
        parts.push(combined.slice(lastIndex, match.index))
      }

      const sourceNum = match[1] ? parseInt(match[1], 10) : parseInt(match[2], 10)
      const source = sources.find(s => s.index === sourceNum)

      if (source) {
        parts.push(
          <CitationChip
            key={`cite-${match.index}`}
            source={source}
            onClick={onCitationClick}
          />
        )
      } else {
        // Source not found — render as plain text (honest, no fabrication)
        parts.push(match[0])
      }

      lastIndex = match.index + match[0].length
    }

    // Add remaining text
    if (lastIndex < combined.length) {
      parts.push(combined.slice(lastIndex))
    }

    // Join string parts with markdown rendering
    const rendered: JSX.Element[] = []
    let textBuffer = ''
    for (const part of parts) {
      if (typeof part === 'string') {
        textBuffer += part
      } else {
        if (textBuffer) {
          rendered.push(<MarkdownRenderer key={`md-${rendered.length}`} content={textBuffer} />)
          textBuffer = ''
        }
        rendered.push(part)
      }
    }
    if (textBuffer) {
      rendered.push(<MarkdownRenderer key={`md-${rendered.length}`} content={textBuffer} />)
    }

    return <>{rendered}</>
  }

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}>
      <div className={`max-w-[80%] px-4 py-3 rounded-2xl text-sm
        ${isUser
          ? 'bg-primary-600 text-white rounded-tr-sm'
          : 'bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 text-neutral-800 dark:text-neutral-100 rounded-tl-sm'
        }`}>
        {renderContent()}
      </div>
    </div>
  )
}
