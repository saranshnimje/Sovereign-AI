/**
 * Zustand auth store.
 * Access token lives only in memory (not localStorage) to prevent XSS theft.
 * The httpOnly refresh cookie is managed by the browser automatically.
 */
import { create } from 'zustand'
import type { UserResponse } from '../api/auth'

interface AuthState {
  accessToken: string | null
  user: UserResponse | null
  setToken: (token: string) => void
  setUser: (user: UserResponse) => void
  clear: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  user: null,
  setToken: (token) => set({ accessToken: token }),
  setUser: (user) => set({ user }),
  clear: () => set({ accessToken: null, user: null }),
}))
