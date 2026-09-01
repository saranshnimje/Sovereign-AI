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
import KnowledgeBasesPage from './pages/KnowledgeBasesPage'
import AgentsPage from './pages/AgentsPage'
import ToolsPage from './pages/ToolsPage'
import IncidentsPage from './pages/IncidentsPage'
import DataPage from './pages/DataPage'
import ApprovalsPage from './pages/ApprovalsPage'
import SettingsPage from './pages/SettingsPage'

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
      authApi
        .me()
        .then((u) => setUser(u))
        .catch(() => {})
        .finally(() => setReady(true))
      return
    }

    api.post('/auth/refresh')
      .then((r) => {
        setToken(r.data.access_token)
        return authApi.me()
      })
      .then((u) => setUser(u))
      .catch(() => {})
      .finally(() => setReady(true))
  }, [])

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-navy-950">
        <div className="text-center">
          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-cyan-500 to-cyan-700 flex items-center justify-center text-white font-bold text-lg mx-auto mb-3 shadow-glow-cyan">S</div>
          <div className="animate-spin h-6 w-6 border-2 border-cyan-500 border-t-transparent rounded-full mx-auto" aria-label="Loading" />
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
            <Route path="/knowledge" element={<KnowledgeBasesPage />} />
            <Route path="/agents" element={<AgentsPage />} />
            <Route path="/models" element={<ModelsPage />} />
            <Route path="/providers" element={<ProvidersPage />} />
            <Route path="/tools" element={<ToolsPage />} />
            <Route path="/incidents" element={<IncidentsPage />} />
            <Route path="/data" element={<DataPage />} />
            <Route path="/approvals" element={<ApprovalsPage />} />
            <Route
              path="/audit"
              element={
                <RequireRole roles={['admin']}>
                  <AuditPage />
                </RequireRole>
              }
            />
            <Route
              path="/settings"
              element={
                <RequireRole roles={['admin']}>
                  <SettingsPage />
                </RequireRole>
              }
            />

            {/* 404 fallback */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </AppBootstrap>
    </BrowserRouter>
  )
}
