/**
 * Root application component.
 * Sets up React Router, auth guards, and the app shell.
 */
import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import api from './api/client'
import { authApi } from './api/auth'
import { useAuthStore } from './stores/authStore'
import AppShell from './components/layout/AppShell'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import ChatPage from './pages/ChatPage'
import AuditPage from './pages/AuditPage'
import ModelsPage from './pages/ModelsPage'
import ProvidersPage from './pages/ProvidersPage'

// ------------------------------------------------------------------
// Protected route wrapper — redirects to /login if not authed
// ------------------------------------------------------------------
function RequireAuth({ children }: { children: React.ReactNode }) {
  const { accessToken } = useAuthStore()
  const location = useLocation()

  if (!accessToken) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }
  return <>{children}</>
}

// ------------------------------------------------------------------
// Role guard — redirects to dashboard if role insufficient
// ------------------------------------------------------------------
function RequireRole({
  children,
  roles,
}: {
  children: React.ReactNode
  roles: string[]
}) {
  const user = useAuthStore((s) => s.user)
  if (!user || !roles.includes(user.role)) {
    return <Navigate to="/" replace />
  }
  return <>{children}</>
}

// ------------------------------------------------------------------
// App bootstrap — tries to restore session via refresh token
// ------------------------------------------------------------------
function AppBootstrap({ children }: { children: React.ReactNode }) {
  const { accessToken, setToken, setUser } = useAuthStore()
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (accessToken) {
      // Already have token — just fetch user
      authApi
        .me()
        .then((u) => setUser(u))
        .catch(() => {})
        .finally(() => setReady(true))
      return
    }

    // Try refresh (uses httpOnly cookie)
    // Wrap in try/catch so a missing/expired cookie doesn't log a console error
    api.post('/auth/refresh')
      .then((r) => {
        setToken(r.data.access_token)
        return authApi.me()
      })
      .then((u) => setUser(u))
      .catch(() => {
        // No valid session — login page will handle this silently
      })
      .finally(() => setReady(true))
  }, [])

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-neutral-50 dark:bg-neutral-900">
        <div className="text-center">
          <div className="text-4xl mb-3">🛡️</div>
          <div
            className="animate-spin h-6 w-6 border-2 border-primary-600 border-t-transparent rounded-full mx-auto"
            aria-label="Loading"
          />
        </div>
      </div>
    )
  }

  return <>{children}</>
}

// ------------------------------------------------------------------
// Route definitions
// ------------------------------------------------------------------
export default function App() {
  return (
    <BrowserRouter>
      <AppBootstrap>
        <Routes>
          {/* Public */}
          <Route path="/login" element={<LoginPage />} />

          {/* Protected — inside app shell */}
          <Route
            element={
              <RequireAuth>
                <AppShell />
              </RequireAuth>
            }
          >
            <Route path="/" element={<DashboardPage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/chat/:convId" element={<ChatPage />} />
            <Route
              path="/audit"
              element={
                <RequireRole roles={['admin']}>
                  <AuditPage />
                </RequireRole>
              }
            />
            <Route path="/models" element={<ModelsPage />} />
            <Route path="/providers" element={<ProvidersPage />} />

            {/* 404 fallback */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </AppBootstrap>
    </BrowserRouter>
  )
}
