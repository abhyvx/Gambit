import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useTheme } from '../context/ThemeContext'
import {
  disconnectPortfolioSession,
  authDeleteAccount,
  connectStakeApiToken,
  retryStakeTokenSync,
  fetchPortfolioState,
} from '../api'
import { useEntryReady } from '../components/EntryScreen'
import './pages.css'

export default function SettingsPage() {
  useEntryReady()
  const { user, openAuth, logout } = useAuth()
  const { theme, setTheme, isLight } = useTheme()
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const [stakeToken, setStakeToken] = useState('')
  const [connection, setConnection] = useState(null)

  const refreshConn = async () => {
    try {
      const st = await fetchPortfolioState()
      setConnection(st?.connection || null)
      return st
    } catch {
      return null
    }
  }

  const clearStake = async () => {
    setBusy('stake')
    setMsg('')
    try {
      await disconnectPortfolioSession()
      setConnection(null)
      setMsg('Stake token removed from this account.')
    } catch (e) {
      setMsg(e?.message || 'Could not clear Stake token.')
    } finally {
      setBusy('')
    }
  }

  const saveToken = async () => {
    if (!user) {
      openAuth('login')
      return
    }
    setBusy('connect')
    setMsg('')
    try {
      const next = await connectStakeApiToken(stakeToken)
      setConnection(next?.connection || null)
      setStakeToken('')
      setMsg(next?.connection?.last_sync_message || 'Token saved.')
      if (next?.connection?.last_sync_status === 'queued') {
        const poll = setInterval(() => {
          refreshConn().then((st) => {
            const s = st?.connection?.last_sync_status
            if (s && s !== 'queued') {
              clearInterval(poll)
              setMsg(st?.connection?.last_sync_message || '')
            }
          })
        }, 8000)
        setTimeout(() => clearInterval(poll), 180000)
      }
    } catch (e) {
      setMsg(e?.message || 'Could not save Stake token.')
    } finally {
      setBusy('')
    }
  }

  const retryImport = async () => {
    setBusy('retry')
    setMsg('')
    try {
      const next = await retryStakeTokenSync()
      setConnection(next?.connection || null)
      setMsg(next?.connection?.last_sync_message || 'Import re-queued.')
    } catch (e) {
      setMsg(e?.message || 'Could not retry import.')
    } finally {
      setBusy('')
    }
  }

  const removeAccount = async () => {
    if (!window.confirm('Delete your GAMBIT account and private journal on this server? This cannot be undone.')) return
    setBusy('delete')
    setMsg('')
    try {
      await authDeleteAccount()
      await logout()
      setMsg('Account deleted.')
    } catch (e) {
      setMsg(e?.message || 'Could not delete account.')
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="page settings-page account-page">
      <header className="page-header">
        <div>
          <h1>Account</h1>
          <p className="subtitle">
            Profile, Stake token, and privacy. Recs come from the model desk, not from style presets.
          </p>
        </div>
      </header>

      <section className="panel">
        <h2 className="panel-title">Profile</h2>
        {user ? (
          <div className="settings-account">
            <p><strong>{user.name || 'You'}</strong></p>
            <p className="muted">{user.email}</p>
            <div className="settings-actions">
              <button type="button" className="refresh-btn" onClick={logout}>Sign out</button>
              <button type="button" className="refresh-btn danger" disabled={busy === 'delete'} onClick={removeAccount}>
                {busy === 'delete' ? 'Deleting…' : 'Delete account'}
              </button>
            </div>
          </div>
        ) : (
          <div className="settings-account">
            <p className="muted">Sign in so your journal and Stake token stay private to you.</p>
            <div className="settings-actions">
              <button type="button" className="refresh-btn" onClick={() => openAuth('login')}>Sign in</button>
              <button type="button" className="refresh-btn" onClick={() => openAuth('signup')}>Create account</button>
            </div>
          </div>
        )}
      </section>

      <section className="panel">
        <h2 className="panel-title">Appearance</h2>
        <p className="panel-desc">Dark is the default. Light mode uses the same layout with a brighter palette.</p>
        <div className="theme-choice-row" role="group" aria-label="Color theme">
          <button
            type="button"
            className={`theme-choice ${!isLight ? 'is-active' : ''}`}
            aria-pressed={!isLight}
            onClick={() => setTheme('dark')}
          >
            Dark
          </button>
          <button
            type="button"
            className={`theme-choice ${isLight ? 'is-active' : ''}`}
            aria-pressed={isLight}
            onClick={() => setTheme('light')}
          >
            Light
          </button>
        </div>
        <p className="muted">Current: {theme}</p>
      </section>

      <section className="panel">
        <h2 className="panel-title">Stake API token</h2>
        <p className="panel-desc">
          Paste the token from Stake → Settings → Security → API Tokens. It is sealed and stored only on your signed-in account.
        </p>
        {!user ? (
          <p className="muted">Sign in to attach a token.</p>
        ) : (
          <>
            <input
              className="stake-token-input"
              type="password"
              autoComplete="off"
              placeholder="Stake API token"
              value={stakeToken}
              onChange={(e) => setStakeToken(e.target.value.trim())}
            />
            <div className="settings-actions">
              <button
                type="button"
                className="refresh-btn"
                disabled={busy === 'connect' || !stakeToken}
                onClick={saveToken}
              >
                {busy === 'connect' ? 'Saving…' : 'Save token'}
              </button>
              <button type="button" className="refresh-btn" disabled={busy === 'retry'} onClick={retryImport}>
                {busy === 'retry' ? 'Retrying…' : 'Retry import'}
              </button>
              <button type="button" className="refresh-btn" disabled={busy === 'stake'} onClick={clearStake}>
                {busy === 'stake' ? 'Clearing…' : 'Remove token'}
              </button>
              <Link className="refresh-btn" to="/app/portfolio">Open portfolio</Link>
            </div>
            {connection?.last_sync_message && (
              <p className="muted" role="status">{connection.last_sync_message}</p>
            )}
          </>
        )}
        {msg && <p className="muted" role="status">{msg}</p>}
      </section>

      <section className="panel">
        <h2 className="panel-title">Legal & privacy</h2>
        <div className="settings-actions">
          <Link className="refresh-btn" to="/app/legal/privacy">Privacy</Link>
          <Link className="refresh-btn" to="/app/legal/terms">Terms</Link>
        </div>
        <p className="responsible-note">
          18+ only · Analytics software, not a bookmaker · Bet only what you can afford to lose.
        </p>
      </section>

      {user?.is_admin && (
        <section className="panel">
          <h2 className="panel-title">Administration</h2>
          <p className="panel-desc">User roster and sync status (no raw tokens).</p>
          <Link className="refresh-btn" to="/app/admin">Open admin</Link>
        </section>
      )}
    </div>
  )
}
