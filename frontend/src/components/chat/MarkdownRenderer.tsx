import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSanitize from 'rehype-sanitize'

/**
 * Safe markdown renderer for assistant responses.
 * Uses rehype-sanitize to strip dangerous HTML/script content.
 * XSS protection: rehype-sanitize defaults strip <script>, <iframe>,
 * event handlers, and all non-standard HTML tags.
 */
export default function MarkdownRenderer({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeSanitize]}
      components={{
        // Style tables for readability
        table: ({ children }) => (
          <div className="overflow-x-auto my-2">
            <table className="min-w-full text-xs border border-neutral-200 dark:border-neutral-600">
              {children}
            </table>
          </div>
        ),
        th: ({ children }) => (
          <th className="px-2 py-1 bg-neutral-100 dark:bg-neutral-700 border border-neutral-200 dark:border-neutral-600 text-left font-semibold">
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td className="px-2 py-1 border border-neutral-200 dark:border-neutral-600">
            {children}
          </td>
        ),
        // Style code blocks
        code: ({ className, children, ...props }) => {
          const isInline = !className
          if (isInline) {
            return (
              <code className="px-1 py-0.5 bg-neutral-100 dark:bg-neutral-700 rounded text-xs font-mono" {...props}>
                {children}
              </code>
            )
          }
          return (
            <div className="relative my-2">
              <pre className="bg-neutral-900 text-neutral-100 rounded-md p-3 overflow-x-auto text-xs">
                <code className={className} {...props}>{children}</code>
              </pre>
            </div>
          )
        },
        // Style headings
        h1: ({ children }) => <h1 className="text-lg font-bold mt-3 mb-1">{children}</h1>,
        h2: ({ children }) => <h2 className="text-base font-bold mt-3 mb-1">{children}</h2>,
        h3: ({ children }) => <h3 className="text-sm font-semibold mt-2 mb-1">{children}</h3>,
        // Style lists
        ul: ({ children }) => <ul className="list-disc list-inside my-1 space-y-0.5">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal list-inside my-1 space-y-0.5">{children}</ol>,
        // Style blockquotes
        blockquote: ({ children }) => (
          <blockquote className="border-l-3 border-primary-400 pl-3 my-2 italic text-neutral-600 dark:text-neutral-300">
            {children}
          </blockquote>
        ),
        // Style links
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noopener noreferrer"
            className="text-primary-600 hover:underline">{children}</a>
        ),
        // Style horizontal rules
        hr: () => <hr className="my-3 border-neutral-200 dark:border-neutral-600" />,
        // Style paragraphs
        p: ({ children }) => <p className="my-1 leading-relaxed">{children}</p>,
      }}
    >
      {content}
    </ReactMarkdown>
  )
}
