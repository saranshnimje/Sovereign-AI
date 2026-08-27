import { useEffect } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../../stores/authStore'
import { useUIStore } from '../../stores/uiStore'
import { authApi } from '../../api/auth'
import ToastContainer from '../ui/ToastContainer'
import StatusPill from '../ui/StatusPill'

const NAV_ITEMS = [
  { to: '/',          icon: '📊', label: 'Overview',        roles: ['viewer','analyst','admin'] },
  { to: '/chat',      icon: '💬', label: 'AI Chat',         roles: ['viewer','analyst','admin'] },
  { to: '/models',    icon: '🧩', label: 'Models',          roles: ['viewer','analyst','admin'] },
  { to: '/providers', icon: '⚡', label: 'LLM Providers',   roles: ['viewer','analyst','admin'] },
  { to: '/audit',     icon: '📋', label: 'Audit Log',       roles: ['admin'] },
]

export default function AppShell() {
  const { user, clear } = useAuthStore()
  const { sidebarOpen, setSidebarOpen, toggleDarkMode, darkMode } = useUIStore()
  const location = useLocation()
  const navigate = useNavigate()

  const role = user?.role ?? 'viewer'
  const navItems = NAV_ITEMS.filter((n) => n.roles.includes(role))

  const handleLogout = async () => {
    try { await authApi.logout() } catch { /* ignore */ }
    clear()
    navigate('/login')
  }

  return (
    <div className="flex h-screen overflow-hidden bg-[#030a03]">
      {/* ── Sidebar ──────────────────────────────────────────── */}
      <aside
        className={`${sidebarOpen ? 'w-56' : 'w-14'} flex-shrink-0 bg-[#060f06] border-r border-green-900/20 flex flex-col transition-all duration-200 z-30`}
        aria-label="Sidebar navigation"
      >
        {/* Logo */}
        <div className="flex items-center gap-2.5 px-3 py-4 border-b border-green-900/20">
          <div className="w-8 h-8 rounded-lg bg-green-600 flex items-center justify-center text-white font-bold text-sm flex-shrink-0">S</div>
          {sidebarOpen && <span className="text-green-400 font-semibold text-sm truncate">Sovereign AI</span>}
        </div>

        {/* Nav */}
        <nav className="flex-1 py-3 overflow-y-auto" aria-label="Main navigation">
          {navItems.map((item) => {
            const active = location.pathname === item.to || (item.to !== '/' && location.pathname.startsWith(item.to))
            return (
              <Link key={item.to} to={item.to}
                className={`flex items-center gap-3 mx-2 mb-0.5 px-2.5 py-2 rounded-lg text-sm transition-all
                  ${active
                    ? 'bg-green-600/15 text-green-400 border border-green-600/20 shadow-sm shadow-green-900/10'
                    : 'text-neutral-500 hover:bg-green-900/10 hover:text-neutral-300 border border-transparent'
                  }`}
                aria-current={active ? 'page' : undefined}>
                <span className="text-base flex-shrink-0">{item.icon}</span>
                {sidebarOpen && <span className="truncate">{item.label}</span>}
              </Link>
            )
          })}
        </nav>

        {/* Bottom */}
        {sidebarOpen && (
          <div className="px-3 py-3 border-t border-green-900/20 space-y-3">
            {/* Copilot card */}
            <div className="bg-green-950/30 border border-green-900/20 rounded-lg p-3">
              <p className="text-[10px] text-green-500 font-medium uppercase tracking-wider">Sovereign Copilot</p>
              <p className="text-[10px] text-neutral-500 mt-0.5">AI assistant is online</p>
              <Link to="/chat"
                className="mt-2 flex items-center justify-center gap-1.5 w-full px-3 py-1.5 bg-green-600/20 border border-green-600/30 text-green-400 rounded-md text-xs font-medium hover:bg-green-600/30 transition-colors">
                💬 Chat with AI
              </Link>
            </div>
            {/* User info */}
            {user && (
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-full bg-green-900/40 border border-green-800/30 flex items-center justify-center text-xs text-green-400 font-medium flex-shrink-0">
                  {(user.username || user.email || 'U')[0].toUpperCase()}
                </div>
                <div className="min-w-0">
                  <div className="text-xs text-neutral-300 truncate">{user.username || user.email}</div>
                  <div className="text-[10px] text-green-600 capitalize">{user.role}</div>
                </div>
              </div>
            )}
          </div>
        )}
      </aside>

      {/* ── Main area ────────────────────────────────────────── */}
      <div className="flex flex-col flex-1 overflow-hidden">
        {/* Top bar */}
        <header className="h-14 flex items-center gap-3 px-4 bg-[#060f06]/80 backdrop-blur-sm border-b border-green-900/20 z-20 flex-shrink-0">
          <button onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-1.5 rounded-lg text-neutral-500 hover:bg-green-900/15 hover:text-neutral-300" aria-label="Toggle sidebar">
            ☰
          </button>

          {/* Search bar (decorative) */}
          <div className="hidden md:flex items-center flex-1 max-w-md mx-4">
            <div className="flex items-center gap-2 w-full px-3 py-1.5 bg-[#0a1a0a] border border-green-900/30 rounded-lg text-neutral-500 text-sm">
              <span className="text-xs">🔍</span>
              <span>Search anything…</span>
              <span className="ml-auto text-[10px] bg-green-900/20 px-1.5 py-0.5 rounded text-neutral-600">⌘K</span>
            </div>
          </div>

          <div className="ml-auto flex items-center gap-3">
            <StatusPill />

            {/* Notifications */}
            <button className="relative p-1.5 rounded-lg text-neutral-500 hover:bg-green-900/15 hover:text-neutral-300">
              🔔
              <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-green-500 rounded-full" />
            </button>

            {/* Dark mode */}
            <button onClick={toggleDarkMode}
              className="p-1.5 rounded-lg text-neutral-500 hover:bg-green-900/15 hover:text-neutral-300"
              aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}>
              {darkMode ? '☀️' : '🌙'}
            </button>

            {/* User */}
            {user && (
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-full bg-green-900/40 border border-green-800/30 flex items-center justify-center text-xs text-green-400 font-medium">
                  {(user.username || user.email || 'U')[0].toUpperCase()}
                </div>
                <div className="hidden sm:block">
                  <div className="text-xs text-neutral-300">{user.username}</div>
                  <div className="text-[10px] text-neutral-600 capitalize">{user.role}</div>
                </div>
                <button onClick={handleLogout} className="text-xs text-neutral-500 hover:text-red-400 px-2 py-1 rounded-lg">
                  Logout
                </button>
              </div>
            )}
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-6 bg-[#030a03]">
          <div className="max-w-7xl mx-auto">
            <Outlet />
          </div>
        </main>
      </div>

      <ToastContainer />
    </div>
  )
}
