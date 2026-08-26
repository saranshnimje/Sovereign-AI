/**
 * Timezone-aware date utilities.
 *
 * Backend stores ALL timestamps as naive UTC (no Z suffix) via SQLite
 * CURRENT_TIMESTAMP / func.now(). These helpers ensure correct parsing
 * and display in Asia/Kolkata.
 *
 * Architecture: Store UTC → API returns naive UTC string → parse as UTC → display IST.
 */
const DISPLAY_TZ = 'Asia/Kolkata'

/** Parse a server timestamp string as UTC (appends Z if no timezone indicator). */
export function parseServerDate(s: string): Date {
  if (!s.endsWith('Z') && !s.includes('+') && !/-\d{2}:\d{2}$/.test(s)) {
    return new Date(s + 'Z')
  }
  return new Date(s)
}

/** Format a Date (or server timestamp string) as IST datetime. */
export function formatIST(d: Date | string): string {
  const date = typeof d === 'string' ? parseServerDate(d) : d
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: DISPLAY_TZ,
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
    hour12: true,
  }).format(date)
}

/** Format as IST date only (e.g. "25 Aug 2026"). */
export function formatISTDate(d: Date | string): string {
  const date = typeof d === 'string' ? parseServerDate(d) : d
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: DISPLAY_TZ,
    year: 'numeric', month: 'short', day: 'numeric',
  }).format(date)
}

/** Format as IST time only (e.g. "07:30 pm"). */
export function formatISTTime(d: Date | string): string {
  const date = typeof d === 'string' ? parseServerDate(d) : d
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: DISPLAY_TZ,
    hour: '2-digit', minute: '2-digit',
    hour12: true,
  }).format(date)
}

/** Get calendar date components in IST for grouping (Today/Yesterday/Older). */
export function istDateParts(d: Date | string): { y: number; m: number; day: number } {
  const date = typeof d === 'string' ? parseServerDate(d) : d
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: DISPLAY_TZ, year: 'numeric', month: '2-digit', day: '2-digit'
  })
  const [y, m, day] = fmt.format(date).split('-').map(Number)
  return { y, m, day }
}

/** Compare two dates by their IST calendar date (ignores time). */
export function sameISTDay(a: Date | string, b: Date | string): boolean {
  const pa = istDateParts(a), pb = istDateParts(b)
  return pa.y === pb.y && pa.m === pb.m && pa.day === pb.day
}

/** Current server UTC timestamp as ISO string (for optimistic UI updates). */
export function nowISO(): string {
  return new Date().toISOString()
}
