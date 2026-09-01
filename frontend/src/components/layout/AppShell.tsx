import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../../stores/authStore'
import { useUIStore } from '../../stores/uiStore'
import { authApi } from '../../api/auth'
import { systemApi, SystemStatus } from '../../api/system'
import ToastContainer from '../ui/ToastContainer'
import StatusPill from '../ui/StatusPill'

const NAV_ITEMS = [
  { to: '/',          icon: HomeIcon,        label: 'Dashboard',      roles: ['viewer','analyst','admin'] },
  { to: '/chat',      icon: ChatIcon,        label: 'Chat',           roles: ['viewer','analyst','admin'] },
  { to: '/knowledge', icon: BookIcon,        label: 'Knowledge Bases', roles: ['viewer','analyst','admin'] },
  { to: '/agents',    icon: AgentIcon,       label: 'Agents',         roles: ['viewer','analyst','admin'] },
  { to: '/models',    icon: ModelIcon,       label: 'Models',         roles: ['viewer','analyst','admin'] },
  { to: '/providers', icon: ProviderIcon,    label: 'Providers',      roles: ['viewer','analyst','admin'] },
  { to: '/tools',     icon: ToolIcon,        label: 'Tools & Plugins',  roles: ['viewer','analyst','admin'] },
  { to: '/incidents', icon: IncidentIcon,    label: 'Incidents',      roles: ['viewer','analyst','admin'] },
  { to: '/data',      icon: DataIcon,        label: 'Data',           roles: ['viewer','analyst','admin'] },
  { to: '/approvals', icon: ApprovalIcon,    label: 'Approvals',      roles: ['analyst','admin'] },
  { to: '/audit',     icon: AuditIcon,       label: 'Audit Log',      roles: ['admin'] },
  { to: '/settings',  icon: SettingsIcon,    label: 'Settings',       roles: ['admin'] },
]

/* ── SVG Icons ─────────────────────────────────────────────────── */
function HomeIcon({ active }: { active?: boolean }) {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={active ? 2 : 1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
    </svg>
  )
}
function ChatIcon({ active }: { active?: boolean }) {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={active ? 2 : 1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 011.037-.443 48.282 48.282 0 005.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
    </svg>
  )
}
function BookIcon({ active }: { active?: boolean }) {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={active ? 2 : 1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
    </svg>
  )
}
function AgentIcon({ active }: { active?: boolean }) {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={active ? 2 : 1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
    </svg>
  )
}
function ModelIcon({ active }: { active?: boolean }) {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={active ? 2 : 1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
    </svg>
  )
}
function ProviderIcon({ active }: { active?: boolean }) {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={active ? 2 : 1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z" />
    </svg>
  )
}
function ToolIcon({ active }: { active?: boolean }) {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={active ? 2 : 1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M11.42 15.17l-5.1-5.1m5.1 5.1L17.25 9.75M11.42 15.17a4.5 4.5 0 10-1.06 1.06l-2.06 2.06a1.5 1.5 0 002.12 0l2.06-2.06zM11.42 15.17l2.06-2.06m-7.16-1.09l5.1-5.1m0 0l2.06-2.06m-2.06 2.06L6.36 7.02" />
    </svg>
  )
}
function IncidentIcon({ active }: { active?: boolean }) {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={active ? 2 : 1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
    </svg>
  )
}
function DataIcon({ active }: { active?: boolean }) {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={active ? 2 : 1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
    </svg>
  )
}
function ApprovalIcon({ active }: { active?: boolean }) {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={active ? 2 : 1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  )
}
function AuditIcon({ active }: { active?: boolean }) {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={active ? 2 : 1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
    </svg>
  )
}
function SettingsIcon({ active }: { active?: boolean }) {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={active ? 2 : 1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  )
}

export default function AppShell() {
  const { user, clear } = useAuthStore()
  const { sidebarOpen, setSidebarOpen, toggleDarkMode, darkMode } = useUIStore()
  const location = useLocation()
  const navigate = useNavigate()
  const [status, setStatus] = useState<SystemStatus | null>(null)

  const role = user?.role ?? 'viewer'
  const navItems = NAV_ITEMS.filter((n) => n.roles.includes(role))

  useEffect(() => {
    const poll = async () => {
      try { const s = await systemApi.status(); setStatus(s) } catch { /* ignore */ }
    }
    poll()
    const id = setInterval(poll, 30000)
    return () => clearInterval(id)
  }, [])

  const handleLogout = async () => {
    try { await authApi.logout() } catch { /* ignore */ }
    clear()
    navigate('/login')
  }

  return (
    <div className="flex h-screen overflow-hidden bg-navy-950">
      {/* ── Sidebar ──────────────────────────────────────────── */}
      <aside
        className={`${sidebarOpen ? 'w-60' : 'w-16'} flex-shrink-0 bg-surface border-r border-surface-border flex flex-col transition-all duration-200 z-30`}
        aria-label="Sidebar navigation"
      >
        {/* Logo */}
        <div className="flex items-center gap-3 px-4 py-4 border-b border-surface-border">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500 to-cyan-700 flex items-center justify-center text-white font-bold text-sm flex-shrink-0 shadow-glow-cyan">
            S
          </div>
          {sidebarOpen && (
            <div>
              <span className="text-cyan-400 font-semibold text-sm">Sovereign AI</span>
              <p className="text-[9px] text-neutral-500">Workbench v2.0</p>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 py-3 overflow-y-auto px-2" aria-label="Main navigation">
          <div className="space-y-0.5">
            {navItems.map((item) => {
              const active = location.pathname === item.to || (item.to !== '/' && location.pathname.startsWith(item.to))
              const Icon = item.icon
              return (
                <Link key={item.to} to={item.to}
                  className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all
                    ${active
                      ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20'
                      : 'text-neutral-500 hover:bg-surface-muted hover:text-neutral-300 border border-transparent'
                    }`}
                  aria-current={active ? 'page' : undefined}>
                  <span className="flex-shrink-0"><Icon active={active} /></span>
                  {sidebarOpen && <span className="truncate">{item.label}</span>}
                </Link>
              )
            })}
          </div>
        </nav>

        {/* Bottom */}
        {sidebarOpen && (
          <div className="px-3 py-3 border-t border-surface-border space-y-3">
            {/* Status card */}
            <div className="bg-surface-overlay rounded-lg p-3 border border-surface-border">
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${status?.status === 'healthy' ? 'bg-success-500' : status?.status === 'degraded' ? 'bg-warning-500' : 'bg-danger-500'}`} />
                <p className="text-[10px] text-neutral-400 font-medium">
                  {status?.status === 'healthy' ? 'All Systems Operational' : status?.status === 'degraded' ? 'Degraded' : 'Checking...'}
                </p>
              </div>
              {status?.services && (
                <div className="mt-2 space-y-1">
                  {Object.entries(status.services).map(([name, svc]) => (
                    <div key={name} className="flex items-center justify-between">
                      <span className="text-[9px] text-neutral-500 capitalize">{name}</span>
                      <span className={`text-[9px] ${svc.status === 'up' ? 'text-success-500' : 'text-danger-500'}`}>
                        {svc.status === 'up' ? 'Online' : 'Offline'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* User info */}
            {user && (
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-cyan-600 to-cyan-800 flex items-center justify-center text-xs text-white font-medium flex-shrink-0 border border-cyan-500/30">
                  {(user.username || user.email || 'U')[0].toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-xs text-neutral-200 truncate">{user.username || user.email}</div>
                  <div className="text-[10px] text-cyan-500 capitalize">{user.role}</div>
                </div>
                <button onClick={handleLogout} className="text-[10px] text-neutral-500 hover:text-danger-500 px-1.5 py-0.5 rounded transition-colors">
                  Logout
                </button>
              </div>
            )}
          </div>
        )}
      </aside>

      {/* ── Main area ────────────────────────────────────────── */}
      <div className="flex flex-col flex-1 overflow-hidden">
        {/* Top bar */}
        <header className="h-14 flex items-center gap-3 px-4 bg-surface/80 backdrop-blur-sm border-b border-surface-border z-20 flex-shrink-0">
          <button onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-1.5 rounded-lg text-neutral-500 hover:bg-surface-muted hover:text-neutral-300 transition-colors" aria-label="Toggle sidebar">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d={sidebarOpen ? "M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" : "M3.75 6.75h16.5M3.75 12h16.5M3.75 17.25h16.5"} />
            </svg>
          </button>

          {/* Search bar */}
          <div className="hidden md:flex items-center flex-1 max-w-md mx-4">
            <div className="flex items-center gap-2 w-full px-3 py-1.5 bg-surface-raised border border-surface-border rounded-lg text-neutral-500 text-sm">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
              </svg>
              <span>Search anything...</span>
              <span className="ml-auto text-[10px] bg-surface-muted px-1.5 py-0.5 rounded text-neutral-600 border border-surface-border">Ctrl+K</span>
            </div>
          </div>

          <div className="ml-auto flex items-center gap-3">
            <StatusPill />

            {/* Notifications */}
            <button className="relative p-1.5 rounded-lg text-neutral-500 hover:bg-surface-muted hover:text-neutral-300 transition-colors">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
              </svg>
              <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-cyan-500 rounded-full" />
            </button>

            {/* Dark mode */}
            <button onClick={toggleDarkMode}
              className="p-1.5 rounded-lg text-neutral-500 hover:bg-surface-muted hover:text-neutral-300 transition-colors"
              aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}>
              {darkMode ? (
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" />
                </svg>
              ) : (
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
                </svg>
              )}
            </button>

            {/* User */}
            {user && (
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-full bg-gradient-to-br from-cyan-600 to-cyan-800 flex items-center justify-center text-xs text-white font-medium border border-cyan-500/30">
                  {(user.username || user.email || 'U')[0].toUpperCase()}
                </div>
                <div className="hidden sm:block">
                  <div className="text-xs text-neutral-200">{user.username}</div>
                  <div className="text-[10px] text-cyan-500 capitalize">{user.role}</div>
                </div>
              </div>
            )}
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-6 bg-navy-950">
          <div className="max-w-7xl mx-auto">
            <Outlet />
          </div>
        </main>
      </div>

      <ToastContainer />
    </div>
  )
}
