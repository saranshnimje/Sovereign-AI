import { create } from 'zustand'

interface UIState {
  sidebarOpen: boolean
  darkMode: boolean
  toasts: Toast[]
  setSidebarOpen: (v: boolean) => void
  toggleDarkMode: () => void
  addToast: (toast: Omit<Toast, 'id'>) => void
  removeToast: (id: string) => void
}

export interface Toast {
  id: string
  type: 'success' | 'error' | 'warning' | 'info'
  title: string
  message?: string
}

const savedDark = localStorage.getItem('darkMode')
const isDark = savedDark === null ? true : savedDark === 'true'

export const useUIStore = create<UIState>((set) => ({
  sidebarOpen: true,
  darkMode: isDark,
  toasts: [],

  setSidebarOpen: (v) => set({ sidebarOpen: v }),

  toggleDarkMode: () =>
    set((s) => {
      const next = !s.darkMode
      localStorage.setItem('darkMode', String(next))
      if (next) document.documentElement.classList.add('dark')
      else document.documentElement.classList.remove('dark')
      return { darkMode: next }
    }),

  addToast: (toast) => {
    const id = crypto.randomUUID()
    set((s) => ({ toasts: [...s.toasts, { ...toast, id }] }))
    const delay = toast.type === 'error' ? 8000 : 5000
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
    }, delay)
  },

  removeToast: (id) =>
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

if (isDark) document.documentElement.classList.add('dark')
