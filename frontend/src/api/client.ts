/**
 * Central Axios instance.
 * - Injects Bearer token from auth store on every request
 * - Handles 401 by attempting token refresh, then retrying
 */
import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '../stores/authStore'

// When deploying frontend and backend on separate origins (e.g. Vercel + Render),
// set VITE_API_URL to the backend base (e.g. https://my-backend.onrender.com).
// In Docker / local dev this is left unset and requests go to the same origin.
export const API_BASE = import.meta.env.VITE_API_URL || ''

const api = axios.create({
  baseURL: `${API_BASE}/api/v1`,
  withCredentials: true,   // send httpOnly refresh cookie
  headers: { 'Content-Type': 'application/json' },
})

// Attach access token
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = useAuthStore.getState().accessToken
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

let _refreshing = false
let _queue: Array<(token: string) => void> = []

// Handle 401 → refresh → retry
api.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    // Never retry a refresh request — that would loop forever
    const isRefreshRequest = original.url?.includes('/auth/refresh')

    if (error.response?.status === 401 && !original._retry && !isRefreshRequest) {
      if (_refreshing) {
        // Wait for ongoing refresh
        return new Promise((resolve) => {
          _queue.push((token) => {
            original.headers.Authorization = `Bearer ${token}`
            resolve(api(original))
          })
        })
      }

      original._retry = true
      _refreshing = true

      try {
        const resp = await api.post('/auth/refresh')
        const newToken: string = resp.data.access_token
        useAuthStore.getState().setToken(newToken)
        _queue.forEach((cb) => cb(newToken))
        _queue = []
        original.headers.Authorization = `Bearer ${newToken}`
        return api(original)
      } catch {
        // Refresh failed — clear auth state and redirect to login
        useAuthStore.getState().clear()
        // Only redirect if not already on login page
        if (!window.location.pathname.startsWith('/login')) {
          window.location.href = '/login'
        }
        return Promise.reject(error)
      } finally {
        _refreshing = false
      }
    }
    return Promise.reject(error)
  },
)

export default api
