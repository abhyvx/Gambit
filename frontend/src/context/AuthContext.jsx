import { createContext, useContext, useEffect, useState } from 'react'
import { authLogin, authLogout, authSignup, fetchAuthMe, getAuthToken } from '../api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [ready, setReady] = useState(false)
  const [authOpen, setAuthOpen] = useState(false)
  const [mode, setMode] = useState('login') // login | signup
  const [form, setForm] = useState({ email: '', password: '', name: '', accept: false })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

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

  const openAuth = (next = 'login') => {
    setMode(next)
    setErr('')
    setAuthOpen(true)
  }

  const submit = async (e) => {
    e?.preventDefault?.()
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
      setUser(out.user)
      setAuthOpen(false)
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

  return (
    <AuthContext.Provider value={{ user, ready, openAuth, logout, authOpen }}>
      {children}
      {authOpen && (
        <div className="auth-modal-backdrop" role="presentation" onClick={() => setAuthOpen(false)}>
          <div className="auth-modal" role="dialog" aria-modal="true" aria-label="Account" onClick={(ev) => ev.stopPropagation()}>
            <h2>{mode === 'signup' ? 'Create account' : 'Sign in'}</h2>
            <p className="muted">
              Private journal + optional Stake API token. Analytics only — we never place bets for you.
            </p>
            <form onSubmit={submit} className="auth-form">
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
              <label>
                <span>Password</span>
                <input
                  type="password"
                  required
                  minLength={6}
                  value={form.password}
                  onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                  autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                />
              </label>
              {mode === 'signup' && (
                <label className="auth-accept">
                  <input
                    type="checkbox"
                    checked={form.accept}
                    onChange={(e) => setForm((f) => ({ ...f, accept: e.target.checked }))}
                  />
                  <span>
                    I am 18+ and accept the{' '}
                    <a href="/app/legal/terms" onClick={() => setAuthOpen(false)}>Terms</a>
                    {' '}and{' '}
                    <a href="/app/legal/privacy" onClick={() => setAuthOpen(false)}>Privacy</a>
                    {' '}policy.
                  </span>
                </label>
              )}
              {err && <p className="auth-error" role="alert">{err}</p>}
              <button type="submit" className="refresh-btn" disabled={busy}>
                {busy ? 'Working…' : (mode === 'signup' ? 'Create account' : 'Sign in')}
              </button>
            </form>
            <button
              type="button"
              className="auth-switch"
              onClick={() => { setMode(mode === 'signup' ? 'login' : 'signup'); setErr('') }}
            >
              {mode === 'signup' ? 'Already have an account? Sign in' : 'Need an account? Create one'}
            </button>
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
