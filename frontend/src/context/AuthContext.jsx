import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { authLogin, authLogout, authSignup, fetchAuthMe, getAuthToken } from '../api'

const AuthContext = createContext(null)

const DEMO_HINTS = {
  'demo.winner@gambit.test': 'DemoWinner12!',
  'demo.builder@gambit.test': 'DemoBuilder12!',
  'demo.learner@gambit.test': 'DemoLearner12!',
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [ready, setReady] = useState(false)
  const [authOpen, setAuthOpen] = useState(false)
  const [mode, setMode] = useState('login') // login | signup | forgot
  const [form, setForm] = useState({ email: '', password: '', name: '', accept: false })
  const [showPassword, setShowPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [forgotMsg, setForgotMsg] = useState('')
  const dialogRef = useRef(null)

  useEffect(() => {
    let mounted = true
    ;(async () => {
      if (!getAuthToken()) {
        if (mounted) setReady(true)
        return
      }
      try {
        const me = await fetchAuthMe()
        if (mounted) setUser(me?.user || null)
      } catch {
        if (mounted) setUser(null)
      } finally {
        if (mounted) setReady(true)
      }
    })()
    return () => { mounted = false }
  }, [])

  const closeAuth = () => {
    setAuthOpen(false)
    setErr('')
    setForgotMsg('')
    setShowPassword(false)
  }

  const openAuth = (next = 'login') => {
    setMode(next)
    setErr('')
    setForgotMsg('')
    setShowPassword(false)
    setAuthOpen(true)
  }

  const submit = async (e) => {
    e?.preventDefault?.()
    if (mode === 'forgot') {
      const email = (form.email || '').trim().toLowerCase()
      if (!email || !email.includes('@')) {
        setErr('Enter the email on your account.')
        return
      }
      const demoPw = DEMO_HINTS[email]
      if (demoPw) {
        setForgotMsg(`Demo account password: ${demoPw}`)
        setErr('')
        return
      }
      setForgotMsg('')
      setErr(
        'Email password reset is not set up yet. Use a demo account from the Guide, or contact the site owner if you are locked out.'
      )
      return
    }
    if (mode === 'signup' && !form.accept) {
      setErr('Accept Privacy and Terms to create an account.')
      return
    }
    setBusy(true)
    setErr('')
    try {
      const out = mode === 'signup'
        ? await authSignup(form)
        : await authLogin(form)
      try {
        const me = await fetchAuthMe()
        setUser(me?.user || out.user)
      } catch {
        setUser(out.user)
      }
      closeAuth()
      setForm({ email: '', password: '', name: '', accept: false })
    } catch (ex) {
      setErr(ex?.message || 'Auth failed')
    } finally {
      setBusy(false)
    }
  }

  const logout = async () => {
    await authLogout()
    setUser(null)
  }

  // Only close when the press starts on the backdrop (not after drag-select mouseup).
  const onBackdropMouseDown = (e) => {
    if (e.target === e.currentTarget) closeAuth()
  }

  return (
    <AuthContext.Provider value={{ user, ready, openAuth, logout, authOpen }}>
      {children}
      {authOpen && (
        <div
          className="auth-modal-backdrop"
          role="presentation"
          onMouseDown={onBackdropMouseDown}
        >
          <div
            ref={dialogRef}
            className="auth-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Account"
            onMouseDown={(ev) => ev.stopPropagation()}
          >
            <div className="auth-modal-head">
              <h2>
                {mode === 'signup' ? 'Create account' : mode === 'forgot' ? 'Forgot password' : 'Sign in'}
              </h2>
              <button
                type="button"
                className="auth-close"
                aria-label="Close"
                onClick={closeAuth}
              >
                ×
              </button>
            </div>
            <p className="muted">
              {mode === 'forgot'
                ? 'Enter your account email. Demo accounts can show their password here; real accounts need the site owner until email reset ships.'
                : 'Private journal and optional Stake API token. Analytics only. We never place bets for you.'}
            </p>
            <form onSubmit={submit} className="auth-form" autoComplete="on">
              {mode === 'signup' && (
                <label>
                  <span>Name</span>
                  <input
                    value={form.name}
                    onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                    autoComplete="name"
                  />
                </label>
              )}
              <label>
                <span>Email</span>
                <input
                  type="email"
                  required
                  value={form.email}
                  onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                  autoComplete="email"
                />
              </label>
              {mode !== 'forgot' && (
                <label className="auth-password-label">
                  <span>Password</span>
                  <div className="auth-password-row">
                    <input
                      type={showPassword ? 'text' : 'password'}
                      required
                      minLength={mode === 'signup' ? 10 : 6}
                      value={form.password}
                      onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                      autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                    />
                    <button
                      type="button"
                      className="auth-show-pw"
                      onClick={() => setShowPassword((v) => !v)}
                      aria-pressed={showPassword}
                    >
                      {showPassword ? 'Hide' : 'Show'}
                    </button>
                  </div>
                  {mode === 'signup' && (
                    <small className="muted">At least 10 characters.</small>
                  )}
                </label>
              )}
              {mode === 'signup' && (
                <label className="auth-accept">
                  <input
                    type="checkbox"
                    checked={form.accept}
                    onChange={(e) => setForm((f) => ({ ...f, accept: e.target.checked }))}
                  />
                  <span>
                    I am 18+ and accept the{' '}
                    <a href="/app/legal/terms" target="_blank" rel="noreferrer">Terms</a>
                    {' '}and{' '}
                    <a href="/app/legal/privacy" target="_blank" rel="noreferrer">Privacy</a>
                    {' '}policy.
                  </span>
                </label>
              )}
              {err && <p className="auth-error" role="alert">{err}</p>}
              {forgotMsg && <p className="auth-forgot-ok" role="status">{forgotMsg}</p>}
              <button type="submit" className="refresh-btn" disabled={busy}>
                {busy
                  ? 'Working…'
                  : mode === 'signup'
                    ? 'Create account'
                    : mode === 'forgot'
                      ? 'Look up account'
                      : 'Sign in'}
              </button>
            </form>
            <div className="auth-footer-links">
              {mode === 'login' && (
                <button
                  type="button"
                  className="auth-switch"
                  onClick={() => { setMode('forgot'); setErr(''); setForgotMsg(''); }}
                >
                  Forgot password?
                </button>
              )}
              {mode === 'forgot' && (
                <button
                  type="button"
                  className="auth-switch"
                  onClick={() => { setMode('login'); setErr(''); setForgotMsg(''); }}
                >
                  Back to sign in
                </button>
              )}
              {mode !== 'forgot' && (
                <button
                  type="button"
                  className="auth-switch"
                  onClick={() => {
                    setMode(mode === 'signup' ? 'login' : 'signup')
                    setErr('')
                    setForgotMsg('')
                  }}
                >
                  {mode === 'signup' ? 'Already have an account? Sign in' : 'Need an account? Create one'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth requires AuthProvider')
  return ctx
}
