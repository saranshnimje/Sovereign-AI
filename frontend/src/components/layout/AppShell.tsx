import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../../stores/authStore'
import { useUIStore } from '../../stores/uiStore'
import { authApi } from '../../api/auth'
import { approvalBadgeApi } from '../../api/settings'
import ToastContainer from '../ui/ToastContainer'
import StatusPill from '../ui/StatusPill'

const NAV_ITEMS = [
  { to: '/',          icon: '🏠', label: 'Dashboard',      roles: ['viewer','analyst','admin'] },
  { to: '/chat',      icon: '💬', label: 'Chat',           roles: ['viewer','analyst','admin'] },
  { to: '/knowledge-bases', icon: '🧠', label: 'Knowledge Bases', roles: ['viewer','analyst','admin'] },
  { to: '/agents',    icon: '🤖', label: 'Agents',         roles: ['analyst','admin'] },
  { to: '/models',    icon: '🧩', label: 'Models',         roles: ['viewer','analyst','admin'] },
  { to: '/providers', icon: '⚡', label: 'LLM Providers',  roles: ['viewer','analyst','admin'] },
  { to: '/tools',     icon: '🔧', label: 'Tools',          roles: ['viewer','analyst','admin'] },
  { to: '/plugins',   icon: '🔌', label: 'Plugins',        roles: ['viewer','analyst','admin'] },
  { to: '/data',      icon: '🏢', label: 'Data',           roles: ['viewer','analyst','admin'] },
  { to: '/approvals', icon: '✅', label: 'Approvals',      roles: ['admin'] },
  { to: '/audit',     icon: '📋', label: 'Audit Log',      roles: ['admin'] },
  { to: '/settings',  icon: '⚙️',  label: 'Settings',      roles: ['admin'] },
]

export default function AppShell() {
  const { user, clear } = useAuthStore()
  const { sidebarOpen, setSidebarOpen, toggleDarkMode, darkMode } = useUIStore()
  const location = useLocation()
  const navigate = useNavigate()
  const [pendingApprovals, setPendingApprovals] = useState(0)

  const role = user?.role ?? 'viewer'
  const navItems = NAV_ITEMS.filter((n) => n.roles.includes(role))

  // Poll approval count for admin badge
  useEffect(() => {
    if (role !== 'admin') return
    const poll = () => approvalBadgeApi.count().then(r => setPendingApprovals(r.count))
    poll()
    const id = setInterval(poll, 30_000)
    return () => clearInterval(id)
  }, [role])

  const handleLogout = async () => {
    try { await authApi.logout() } catch { /* ignore */ }
    clear()
    navigate('/login')
  }

  return (
    <div className="flex h-screen overflow-hidden bg-neutral-50 dark:bg-neutral-900">
      {/* ---- Sidebar ---- */}
      <aside
        className={`${sidebarOpen ? 'w-56' : 'w-14'} flex-shrink-0 bg-neutral-900 dark:bg-neutral-950 flex flex-col transition-all duration-200 z-30`}
        aria-label="Sidebar navigation"
      >
        {/* Logo */}
        <div className="flex items-center gap-2 px-3 py-4 border-b border-neutral-700">
          <span className="text-xl">🛡️</span>
          {sidebarOpen && (
            <span className="text-white font-semibold text-sm truncate">
              Sovereign AI
            </span>
          )}
        </div>

        {/* Nav items */}
        <nav className="flex-1 py-3 overflow-y-auto" aria-label="Main navigation">
          {navItems.map((item) => {
            const active = location.pathname === item.to ||
              (item.to !== '/' && location.pathname.startsWith(item.to))
            return (
              <Link
                key={item.to}
                to={item.to}
                className={`flex items-center gap-3 mx-2 mb-1 px-2 py-2 rounded-md text-sm transition-colors
                  ${active
                    ? 'bg-primary-700 text-white'
                    : 'text-neutral-300 hover:bg-neutral-700 hover:text-white'
                  }`}
                aria-current={active ? 'page' : undefined}
              >
                <span className="text-base flex-shrink-0" aria-hidden="true">{item.icon}</span>
                {sidebarOpen && <span className="truncate flex-1">{item.label}</span>}
                {/* Approval badge */}
                {sidebarOpen && item.to === '/approvals' && pendingApprovals > 0 && (
                  <span className="bg-danger-600 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center flex-shrink-0" aria-label={`${pendingApprovals} pending`}>
                    {pendingApprovals > 9 ? '9+' : pendingApprovals}
                  </span>
                )}
              </Link>
            )
          })}
        </nav>

        {/* Bottom: user info */}
        {sidebarOpen && user && (
          <div className="px-3 py-3 border-t border-neutral-700">
            <div className="text-xs text-neutral-400 truncate">{user.email}</div>
            <div className="text-xs text-neutral-500 capitalize">{user.role}</div>
          </div>
        )}
      </aside>

      {/* ---- Main area ---- */}
      <div className="flex flex-col flex-1 overflow-hidden">
        {/* Top bar */}
        <header className="h-14 flex items-center gap-3 px-4 bg-white dark:bg-neutral-900 border-b border-neutral-200 dark:border-neutral-700 z-20 flex-shrink-0">
          {/* Sidebar toggle */}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-1.5 rounded-md text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800"
            aria-label="Toggle sidebar"
          >
            ☰
          </button>

          <span className="font-semibold text-neutral-800 dark:text-neutral-100 text-sm hidden md:block">
            Sovereign AI Workbench
          </span>

          <div className="ml-auto flex items-center gap-3">
            <StatusPill />

            {/* Dark mode toggle */}
            <button
              onClick={toggleDarkMode}
              className="p-1.5 rounded-md text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800"
              aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {darkMode ? '☀️' : '🌙'}
            </button>

            {/* User + logout */}
            {user && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-neutral-600 dark:text-neutral-400 hidden sm:block">
                  {user.username}
                </span>
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium
                  ${user.role === 'admin' ? 'bg-purple-100 text-purple-700' :
                    user.role === 'analyst' ? 'bg-blue-100 text-blue-700' :
                    'bg-neutral-100 text-neutral-600'}`}>
                  {user.role}
                </span>
                <button
                  onClick={handleLogout}
                  className="text-xs text-neutral-500 hover:text-danger-600 px-2 py-1 rounded"
                >
                  Logout
                </button>
              </div>
            )}
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-6 bg-neutral-50 dark:bg-neutral-900">
          <div className="max-w-7xl mx-auto">
            <Outlet />
          </div>
        </main>
      </div>

      {/* Toast stack */}
      <ToastContainer />
    </div>
  )
}
