import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi, DemoUser } from '../api/auth'
import { useAuthStore } from '../stores/authStore'
import SovereignLogo from '../components/ui/SovereignLogo'

const DEMO_ADMIN = {
  username: 'admin',
  email: 'admin@admin.com',
  password: 'admin12345678',
}

export default function LoginPage() {
  const navigate = useNavigate()
  const { setToken, setUser, accessToken } = useAuthStore()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [setupMode, setSetupMode] = useState(false)
  const [username, setUsername] = useState('')
  const [fieldErrors, setFieldErrors] = useState<{email?: string; password?: string; username?: string}>({})

  const [demoUsers, setDemoUsers] = useState<DemoUser[]>([])
  const [demoLoading, setDemoLoading] = useState(true)
  const [demoError, setDemoError] = useState('')

  useEffect(() => { if (accessToken) navigate('/') }, [accessToken])

  useEffect(() => {
    authApi.setupStatus()
      .then((s) => {
        setSetupMode(s.setup_required)
        if (!s.setup_required) {
          setDemoLoading(true)
          authApi.getDemoUsers()
            .then(setDemoUsers)
            .catch(() => setDemoError('Could not load demo accounts'))
            .finally(() => setDemoLoading(false))
        }
      })
      .catch(() => setDemoLoading(false))
  }, [])

  const validate = () => {
    const errs: typeof fieldErrors = {}
    if (!email.trim()) errs.email = 'Email is required'
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) errs.email = 'Enter a valid email'
    if (!password) errs.password = 'Password is required'
    else if (setupMode && password.length < 12) errs.password = 'Password must be at least 12 characters'
    if (setupMode && !username.trim()) errs.username = 'Username is required'
    setFieldErrors(errs)
    return Object.keys(errs).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault(); setError('')
    if (!validate()) return
    setLoading(true)
    try {
      if (setupMode) await authApi.register({ email, username, password })
      const token = await authApi.login({ email, password })
      setToken(token.access_token)
      const user = await authApi.me(); setUser(user); navigate('/')
    } catch (err: any) {
      setError(err?.response?.data?.error?.message || err?.response?.data?.detail || 'Login failed')
    } finally { setLoading(false) }
  }

  const useDemoCredentials = (demo: DemoUser) => {
    if (!demo.has_demo_password || !demo.demo_password) return
    setSetupMode(false)
    setEmail(demo.email)
    setPassword(demo.demo_password)
    setFieldErrors({})
    setError('')
  }

  const fillDemoAdmin = () => {
    setEmail(DEMO_ADMIN.email)
    setPassword(DEMO_ADMIN.password)
    setUsername(DEMO_ADMIN.username)
    setFieldErrors({})
    setError('')
  }

  const inputCls = (hasError?: string) =>
    `w-full rounded-lg border ${hasError ? 'border-danger-500 focus:ring-danger-500' : 'border-surface-border focus:ring-cyan-500 focus:border-cyan-500'} bg-surface px-3 py-2.5 text-sm text-neutral-200 placeholder-neutral-600 shadow-sm focus:outline-none focus:ring-2 transition-colors`

  return (
    <div className="min-h-screen flex items-center justify-center bg-navy-950 p-4">
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
                  required autoComplete="username" placeholder="admin" className={inputCls(fieldErrors.username)} />
                {fieldErrors.username && <p className="text-xs text-danger-500 mt-1">{fieldErrors.username}</p>}
              </div>
            )}

            <div className="mb-4">
              <label htmlFor="email" className="block text-sm font-medium text-neutral-300 mb-1">Email address</label>
              <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                required autoComplete="email" placeholder="you@organisation.gov" className={inputCls(fieldErrors.email)} />
              {fieldErrors.email && <p className="text-xs text-danger-500 mt-1">{fieldErrors.email}</p>}
            </div>

            <div className="mb-6">
              <label htmlFor="password" className="block text-sm font-medium text-neutral-300 mb-1">
                Password {setupMode && <span className="text-neutral-500 font-normal">(min 12 characters)</span>}
              </label>
              <div className="relative">
                <input id="password" type={showPassword ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)}
                  required autoComplete={setupMode ? 'new-password' : 'current-password'} placeholder="••••••••••••"
                  className={`${inputCls(fieldErrors.password)} pr-10`} />
                <button type="button" onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-neutral-500 hover:text-neutral-300 p-1"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}>
                  {showPassword ? (
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" /></svg>
                  ) : (
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
                  )}
                </button>
              </div>
              {fieldErrors.password && <p className="text-xs text-danger-500 mt-1">{fieldErrors.password}</p>}
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
            <>
              <p className="text-xs text-neutral-500 text-center mt-4">New here? Contact your administrator to get an account.</p>

              <div className="mt-6 border-t border-surface-border pt-5">
                <div className="flex items-center gap-2 mb-3">
                  <h3 className="text-sm font-semibold text-neutral-300">SIH Demo Admin</h3>
                  <span className="text-[10px] uppercase tracking-wider bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 rounded px-1.5 py-0.5">Demo</span>
                </div>
                <p className="text-xs text-neutral-500 mb-3">Autofill the admin credentials for your SIH presentation. This only fills the form; it does not sign in automatically.</p>
                <button type="button" onClick={fillDemoAdmin}
                  className="w-full border border-cyan-500/40 text-cyan-400 rounded-lg py-2.5 px-4 text-sm font-medium hover:bg-cyan-500/10 hover:text-cyan-300 transition-colors">
                  Fill Demo Admin Credentials
                </button>
              </div>

              <div className="mt-6 border-t border-surface-border pt-5">
                <div className="flex items-center gap-2 mb-3">
                  <h3 className="text-sm font-semibold text-neutral-300">Demo Credentials</h3>
                  <span className="text-[10px] uppercase tracking-wider bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 rounded px-1.5 py-0.5">Prototype</span>
                </div>
                <p className="text-xs text-neutral-500 mb-3">Click <span className="text-neutral-300">Use Credentials</span> to autofill, then <span className="text-neutral-300">Sign In</span>.</p>

                {demoLoading ? (
                  <div className="flex items-center justify-center py-6 text-neutral-500 text-xs gap-2">
                    <span className="animate-spin h-3.5 w-3.5 border-2 border-neutral-500 border-t-transparent rounded-full" />
                    Loading demo accounts…
                  </div>
                ) : demoError ? (
                  <div className="py-4 text-center text-xs text-danger-500">{demoError}</div>
                ) : demoUsers.length === 0 ? (
                  <div className="py-4 text-center text-xs text-neutral-500">No demo accounts available.</div>
                ) : (
                  <div className="overflow-hidden border border-surface-border rounded-lg">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-surface text-neutral-400 text-left">
                          <th className="px-3 py-2 font-medium">Email</th>
                          <th className="px-3 py-2 font-medium">Password</th>
                          <th className="px-3 py-2 font-medium">Role</th>
                          <th className="px-3 py-2 font-medium text-right">Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-surface-border">
                        {demoUsers.map((demo) => (
                          <tr key={demo.email} className="bg-surface-raised/40">
                            <td className="px-3 py-2 text-neutral-200 break-all">{demo.email}</td>
                            <td className="px-3 py-2 text-neutral-300">
                              {demo.has_demo_password ? demo.demo_password : (
                                <span className="text-neutral-500 italic">Password unavailable</span>
                              )}
                            </td>
                            <td className="px-3 py-2">
                              <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400 text-[10px] uppercase tracking-wide">{demo.role}</span>
                            </td>
                            <td className="px-3 py-2 text-right">
                              {demo.has_demo_password ? (
                                <button type="button" onClick={() => useDemoCredentials(demo)}
                                  className="text-cyan-400 hover:text-cyan-300 font-medium transition-colors">
                                  Use Credentials
                                </button>
                              ) : (
                                <span className="text-neutral-600 text-[10px]">N/A</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        <p className="text-center text-xs text-neutral-600 mt-4">All AI processing runs locally — no data leaves your network.</p>
      </div>
    </div>
  )
}
