/**
 * Generic placeholder for pages that will be built in Phase 2+.
 * Shows the page title and a "coming in next phase" note.
 */
interface Props { title: string; icon: string; phase?: string }

export default function PlaceholderPage({ title, icon, phase = 'Phase 2' }: Props) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center">
      <div className="text-5xl mb-4" aria-hidden="true">{icon}</div>
      <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">{title}</h1>
      <p className="text-neutral-500 dark:text-neutral-400 mt-2 text-sm">
        This feature is implemented in <strong>{phase}</strong>.
      </p>
      <p className="text-xs text-neutral-400 mt-1">
        Phase 1 establishes the foundation — auth, chat, and system status.
      </p>
    </div>
  )
}
