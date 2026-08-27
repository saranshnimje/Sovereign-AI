import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi } from '../api/auth'
import { useAuthStore } from '../stores/authStore'

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

  const inputCls = "w-full rounded-lg border border-green-900/40 bg-[#050e05] px-3 py-2.5 text-sm text-neutral-200 placeholder-neutral-600 shadow-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500"

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#050e05] p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="text-5xl mb-3">🛡️</div>
          <h1 className="text-2xl font-bold text-white">Sovereign AI Workbench</h1>
          <p className="text-sm text-neutral-500 mt-1">Privacy-first on-premise AI platform</p>
        </div>

        <div className="bg-[#0a1a0a] border border-green-900/40 rounded-xl shadow-xl p-8">
          {setupMode && (
            <div className="mb-6 p-3 bg-green-900/20 border border-green-800/30 rounded-lg text-sm text-green-400">
              <strong>First-time setup</strong> — Create your administrator account.
            </div>
          )}

          <h2 className="text-lg font-semibold text-white mb-6">
            {setupMode ? 'Create Admin Account' : 'Sign In'}
          </h2>

          {error && (
            <div className="mb-4 p-3 bg-red-900/20 border border-red-800/40 rounded-lg text-sm text-red-400" role="alert">{error}</div>
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
              className="w-full bg-green-600 text-white rounded-lg py-2.5 px-4 text-sm font-medium hover:bg-green-500 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2 focus:ring-offset-[#0a1a0a] disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
                  {setupMode ? 'Creating account…' : 'Signing in…'}
                </span>
              ) : (setupMode ? 'Create Account & Sign In' : 'Sign In')}
            </button>
          </form>

          {!setupMode && (
            <p className="text-xs text-neutral-500 text-center mt-4">New here? Contact your administrator to get an account.</p>
          )}
        </div>

        <p className="text-center text-xs text-neutral-600 mt-4">🔒 All AI processing runs locally — no data leaves your network.</p>
      </div>
    </div>
  )
}
