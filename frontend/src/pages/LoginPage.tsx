import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi } from '../api/auth'
import { useAuthStore } from '../stores/authStore'
import SovereignLogo from '../components/ui/SovereignLogo'

export default function LoginPage() {
  const navigate = useNavigate()
  const { setToken, setUser, accessToken } = useAuthStore()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [setupMode, setSetupMode] = useState(false)
  const [username, setUsername] = useState('')

  useEffect(() => { if (accessToken) navigate('/') }, [accessToken])
  useEffect(() => { authApi.setupStatus().then((s) => setSetupMode(s.setup_required)).catch(() => {}) }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault(); setError(''); setLoading(true)
    try {
      if (setupMode) await authApi.register({ email, username, password })
      const token = await authApi.login({ email, password })
      setToken(token.access_token)
      const user = await authApi.me(); setUser(user); navigate('/')
    } catch (err: any) {
      setError(err?.response?.data?.error?.message || err?.response?.data?.detail || 'Login failed')
    } finally { setLoading(false) }
  }

  const inputCls = "w-full rounded-lg border border-surface-border bg-surface px-3 py-2.5 text-sm text-neutral-200 placeholder-neutral-600 shadow-sm focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-cyan-500 transition-colors"

  return (
    <div className="min-h-screen flex items-center justify-center bg-navy-950 p-4">
      {/* Background decoration */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-cyan-500/5 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-navy-500/10 rounded-full blur-3xl" />
      </div>

      <div className="w-full max-w-md relative">
        <div className="text-center mb-8">
          <div className="mx-auto mb-4">
            <SovereignLogo size={56} animate={true} />
          </div>
          <h1 className="text-2xl font-bold text-white">Sovereign AI Workbench</h1>
          <p className="text-sm text-neutral-400 mt-1">Privacy-first on-premise AI platform</p>
        </div>

        <div className="bg-surface-raised border border-surface-border rounded-xl shadow-xl p-8">
          {setupMode && (
            <div className="mb-6 p-3 bg-cyan-500/10 border border-cyan-500/30 rounded-lg text-sm text-cyan-400">
              <strong>First-time setup</strong> — Create your administrator account.
            </div>
          )}

          <h2 className="text-lg font-semibold text-white mb-6">
            {setupMode ? 'Create Admin Account' : 'Sign In'}
          </h2>

          {error && (
            <div className="mb-4 p-3 bg-danger-500/10 border border-danger-500/30 rounded-lg text-sm text-danger-500" role="alert">{error}</div>
          )}

          <form onSubmit={handleSubmit} noValidate>
            {setupMode && (
              <div className="mb-4">
                <label htmlFor="username" className="block text-sm font-medium text-neutral-300 mb-1">Username</label>
                <input id="username" type="text" value={username} onChange={(e) => setUsername(e.target.value)}
                  required autoComplete="username" placeholder="admin" className={inputCls} />
              </div>
            )}

            <div className="mb-4">
              <label htmlFor="email" className="block text-sm font-medium text-neutral-300 mb-1">Email address</label>
              <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                required autoComplete="email" placeholder="you@organisation.gov" className={inputCls} />
            </div>

            <div className="mb-6">
              <label htmlFor="password" className="block text-sm font-medium text-neutral-300 mb-1">
                Password {setupMode && <span className="text-neutral-500 font-normal">(min 12 characters)</span>}
              </label>
              <input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                required autoComplete={setupMode ? 'new-password' : 'current-password'} placeholder="••••••••••••" className={inputCls} />
            </div>

            <button type="submit" disabled={loading}
              className="w-full bg-cyan-600 text-white rounded-lg py-2.5 px-4 text-sm font-medium hover:bg-cyan-500 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:ring-offset-2 focus:ring-offset-surface-raised disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-lg shadow-cyan-900/30">
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
                  {setupMode ? 'Creating account...' : 'Signing in...'}
                </span>
              ) : (setupMode ? 'Create Account & Sign In' : 'Sign In')}
            </button>
          </form>

          {!setupMode && (
            <p className="text-xs text-neutral-500 text-center mt-4">New here? Contact your administrator to get an account.</p>
          )}
        </div>

        <p className="text-center text-xs text-neutral-600 mt-4">All AI processing runs locally — no data leaves your network.</p>
      </div>
    </div>
  )
}
