import { useEffect, useRef, useState, useCallback } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist'

pdfjsLib.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjsLib.version}/build/pdf.worker.min.mjs`

interface Props {
  url: string
  filename: string
}

export default function PDFViewer({ url, filename }: Props) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [totalPages, setTotalPages] = useState(0)
  const [scale, setScale] = useState(1.2)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [rendering, setRendering] = useState(false)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const renderTaskRef = useRef<any>(null)

  useEffect(() => {
    let cancelled = false
    const loadPdf = async () => {
      try {
        setLoading(true)
        setError(null)
        const loadingTask = pdfjsLib.getDocument({ url })
        const pdfDoc = await loadingTask.promise
        if (cancelled) return
        setPdf(pdfDoc)
        setTotalPages(pdfDoc.numPages)
        setCurrentPage(1)
      } catch (err) {
        if (!cancelled) setError('Failed to load PDF document')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    loadPdf()
    return () => { cancelled = true }
  }, [url])

  const renderPage = useCallback(async (pageNum: number) => {
    if (!pdf || !canvasRef.current) return
    try {
      setRendering(true)
      if (renderTaskRef.current) {
        renderTaskRef.current.cancel()
        renderTaskRef.current = null
      }
      const page: PDFPageProxy = await pdf.getPage(pageNum)
      const viewport = page.getViewport({ scale })
      const canvas = canvasRef.current
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      canvas.height = viewport.height
      canvas.width = viewport.width
      const renderContext = { canvasContext: ctx, canvas: canvas, viewport }
      const task = page.render(renderContext)
      renderTaskRef.current = task
      await task.promise
      renderTaskRef.current = null
    } catch (err: any) {
      if (err?.name !== 'RenderingCancelledException') {
        console.error('PDF render error:', err)
      }
    } finally {
      setRendering(false)
    }
  }, [pdf, scale])

  useEffect(() => {
    renderPage(currentPage)
  }, [currentPage, renderPage])

  const goToPage = (p: number) => {
    if (p >= 1 && p <= totalPages) setCurrentPage(p)
  }

  const zoomIn = () => setScale(s => Math.min(s + 0.25, 3))
  const zoomOut = () => setScale(s => Math.max(s - 0.25, 0.25))
  const zoomReset = () => setScale(1.2)

  const fitWidth = () => {
    if (containerRef.current && pdf) {
      pdf.getPage(currentPage).then(page => {
        const viewport = page.getViewport({ scale: 1 })
        const containerWidth = containerRef.current!.clientWidth - 40
        setScale(containerWidth / viewport.width)
      })
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="flex flex-col items-center gap-3">
          <div className="animate-spin h-8 w-8 border-2 border-cyan-500 border-t-transparent rounded-full" />
          <p className="text-sm text-neutral-400">Loading PDF...</p>
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
      <div className="flex items-center justify-between px-4 py-2 bg-surface-overlay border-b border-surface-border flex-shrink-0">
        <div className="flex items-center gap-2">
          <button onClick={() => goToPage(currentPage - 1)} disabled={currentPage <= 1}
            className="p-1.5 rounded text-neutral-400 hover:text-white hover:bg-surface-muted disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
            </svg>
          </button>
          <span className="text-xs text-neutral-300 min-w-[80px] text-center">
            {currentPage} / {totalPages}
          </span>
          <button onClick={() => goToPage(currentPage + 1)} disabled={currentPage >= totalPages}
            className="p-1.5 rounded text-neutral-400 hover:text-white hover:bg-surface-muted disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
            </svg>
          </button>
        </div>

        <div className="flex items-center gap-1">
          <button onClick={zoomOut} className="p-1.5 rounded text-neutral-400 hover:text-white hover:bg-surface-muted transition-colors" title="Zoom out">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607zM13.5 10.5H6" />
            </svg>
          </button>
          <button onClick={zoomReset} className="px-2 py-1 text-xs text-neutral-300 rounded hover:bg-surface-muted transition-colors min-w-[48px] text-center">
            {Math.round(scale * 100)}%
          </button>
          <button onClick={zoomIn} className="p-1.5 rounded text-neutral-400 hover:text-white hover:bg-surface-muted transition-colors" title="Zoom in">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607zM13.5 10.5H6" />
            </svg>
          </button>
          <div className="w-px h-4 bg-surface-border mx-1" />
          <button onClick={fitWidth} className="p-1.5 rounded text-neutral-400 hover:text-white hover:bg-surface-muted transition-colors" title="Fit to width">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12" />
            </svg>
          </button>
        </div>

        <div className="text-xs text-neutral-500 truncate max-w-[200px]">{filename}</div>
      </div>

      <div ref={containerRef} className="flex-1 overflow-auto bg-neutral-900 flex justify-center p-5">
        {rendering && (
          <div className="fixed top-16 right-4 z-10">
            <div className="animate-spin h-4 w-4 border-2 border-cyan-500 border-t-transparent rounded-full" />
          </div>
        )}
        <canvas ref={canvasRef} className="shadow-lg rounded" />
      </div>
    </div>
  )
}
