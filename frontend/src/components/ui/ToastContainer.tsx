import { useUIStore } from '../../stores/uiStore'

const STYLES: Record<string, string> = {
  success: 'bg-success-50 border-l-4 border-success-500 text-green-800',
  error:   'bg-danger-100 border-l-4 border-danger-600  text-red-800',
  warning: 'bg-warning-50 border-l-4 border-warning-500 text-yellow-800',
  info:    'bg-blue-50   border-l-4 border-blue-500    text-blue-800',
}
const ICONS: Record<string, string> = {
  success: '✓', error: '✗', warning: '⚠', info: 'ℹ',
}

export default function ToastContainer() {
  const { toasts, removeToast } = useUIStore()
  return (
    <div
      className="fixed top-4 right-4 z-50 flex flex-col gap-2 min-w-72 max-w-sm"
      aria-live="polite"
      aria-atomic="false"
    >
      {toasts.map((t) => (
        <div key={t.id} className={`rounded-lg shadow-lg p-4 ${STYLES[t.type]}`} role="alert">
          <div className="flex items-start gap-2">
            <span aria-hidden="true" className="font-bold text-sm">{ICONS[t.type]}</span>
            <div className="flex-1 min-w-0">
              <p className="font-medium text-sm">{t.title}</p>
              {t.message && <p className="text-xs mt-0.5 opacity-80">{t.message}</p>}
            </div>
            <button
              onClick={() => removeToast(t.id)}
              className="text-current opacity-60 hover:opacity-100 text-sm ml-1"
              aria-label="Dismiss notification"
            >
              ✕
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
