import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi } from '../api/auth'
import { useAuthStore } from '../stores/authStore'

export default function LoginPage() {
  const navigate = useNavigate()
  const { setToken, setUser, accessToken } = useAuthStore()

  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [error, setError]       = useState('')
  const [loading, setLoading]   = useState(false)
  const [setupMode, setSetupMode] = useState(false)
  const [username, setUsername] = useState('')

  // Redirect if already logged in
  useEffect(() => {
    if (accessToken) navigate('/')
  }, [accessToken])

  // Check first-run setup
  useEffect(() => {
    authApi.setupStatus().then((s) => setSetupMode(s.setup_required)).catch(() => {})
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      if (setupMode) {
        // Register first admin
        await authApi.register({ email, username, password })
      }
      const token = await authApi.login({ email, password })
      setToken(token.access_token)
      const user = await authApi.me()
      setUser(user)
      navigate('/')
    } catch (err: any) {
      const msg = err?.response?.data?.error?.message || err?.response?.data?.detail || 'Login failed'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-neutral-50 dark:bg-neutral-900 p-4">
      <div className="w-full max-w-md">
        {/* Logo / heading */}
        <div className="text-center mb-8">
          <div className="text-5xl mb-3">🛡️</div>
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">
            Sovereign AI Workbench
          </h1>
          <p className="text-sm text-neutral-500 mt-1">Privacy-first on-premise AI platform</p>
        </div>

        <div className="bg-white dark:bg-neutral-800 rounded-lg shadow-sm border border-neutral-200 dark:border-neutral-700 p-8">
          {setupMode && (
            <div className="mb-6 p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-md text-sm text-blue-700 dark:text-blue-300">
              <strong>First-time setup</strong> — Create your administrator account to get started.
            </div>
          )}

          <h2 className="text-lg font-semibold text-neutral-800 dark:text-neutral-100 mb-6">
            {setupMode ? 'Create Admin Account' : 'Sign In'}
          </h2>

          {error && (
            <div className="mb-4 p-3 bg-danger-100 border border-danger-200 rounded-md text-sm text-danger-700" role="alert">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} noValidate>
            {setupMode && (
              <div className="mb-4">
                <label htmlFor="username" className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                  Username
                </label>
                <input
                  id="username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  autoComplete="username"
                  placeholder="admin"
                  className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 placeholder-neutral-400 shadow-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                />
              </div>
            )}

            <div className="mb-4">
              <label htmlFor="email" className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Email address
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
                placeholder="you@organisation.gov"
                className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 placeholder-neutral-400 shadow-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              />
            </div>

            <div className="mb-6">
              <label htmlFor="password" className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
                Password {setupMode && <span className="text-neutral-400 font-normal">(min 12 characters)</span>}
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete={setupMode ? 'new-password' : 'current-password'}
                placeholder="••••••••••••"
                className="w-full rounded-md border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-700 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100 placeholder-neutral-400 shadow-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-primary-600 text-white rounded-md py-2 px-4 text-sm font-medium hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" aria-hidden="true" />
                  {setupMode ? 'Creating account…' : 'Signing in…'}
                </span>
              ) : (
                setupMode ? 'Create Account & Sign In' : 'Sign In'
              )}
            </button>
          </form>

          {!setupMode && (
            <p className="text-xs text-neutral-400 text-center mt-4">
              New here? Contact your administrator to get an account.
            </p>
          )}
        </div>

        {/* Privacy note */}
        <p className="text-center text-xs text-neutral-400 mt-4">
          🔒 All AI processing runs locally — no data leaves your network.
        </p>
      </div>
    </div>
  )
}
