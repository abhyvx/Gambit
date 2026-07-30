import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { fetchAdminAccounts, revokeAdminSessions } from '../api'
import { useEntryReady } from '../components/EntryScreen'
import './pages.css'

export default function AdminUsersPage() {
  useEntryReady()
  const { user, ready, openAuth } = useAuth()
  const [rows, setRows] = useState([])
  const [summary, setSummary] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')

  const load = async () => {
    setErr('')
    try {
      const data = await fetchAdminAccounts()
      setRows(data?.accounts || [])
      setSummary(data?.admin_debug?.users || null)
    } catch (e) {
      setErr(e?.message || 'Admin access denied.')
      setRows([])
      setSummary(null)
    }
  }

  useEffect(() => {
    if (user?.is_admin) load()
  }, [user?.is_admin])

  if (!ready) {
    return <div className="page"><p className="muted">Loading account…</p></div>
  }
  if (!user) {
    return (
      <div className="page">
        <p className="muted">Sign in as an admin.</p>
        <button type="button" className="refresh-btn" onClick={() => openAuth('login')}>Sign in</button>
      </div>
    )
  }
  if (!user.is_admin) {
    return (
      <div className="page">
        <p className="muted">This account is not an admin.</p>
        <Link className="refresh-btn" to="/app/account">Back to account</Link>
      </div>
    )
  }

  return (
    <div className="page admin-page">
      <header className="page-header">
        <div>
          <p className="muted" style={{ marginBottom: '0.35rem' }}>
            <Link to="/app/admin">Admin</Link>
            {' / '}
            Users
          </p>
          <h1>Users</h1>
          <p className="subtitle">Account roster only. Stake tokens stay sealed.</p>
        </div>
        <button type="button" className="refresh-btn" onClick={load}>Refresh</button>
      </header>

      <nav className="admin-nav" aria-label="Admin sections">
        <Link className="admin-nav-link" to="/app/admin">Overview</Link>
        <Link className="admin-nav-link is-active" to="/app/admin/users">Users</Link>
      </nav>

      {err && <p className="muted" role="alert">{err}</p>}

      <section className="panel">
        <h2 className="panel-title">Summary</h2>
        <div className="admin-debug-grid">
          <article className="admin-debug-card">
            <ul className="admin-debug-list">
              <li><span>Accounts</span><strong>{summary?.accounts ?? rows.length}</strong></li>
              <li><span>With Stake token</span><strong>{summary?.with_stake_token ?? 0}</strong></li>
              <li><span>Total bets</span><strong>{summary?.bets_total ?? 0}</strong></li>
              <li><span>Active sessions</span><strong>{summary?.active_sessions ?? 0}</strong></li>
            </ul>
          </article>
        </div>
      </section>

      <section className="panel">
        <h2 className="panel-title">Accounts ({rows.length})</h2>
        <div className="admin-table">
          <div className="admin-row admin-row--head">
            <span>User</span>
            <span>Bets</span>
            <span>Token</span>
            <span>Sync</span>
            <span />
          </div>
          {rows.map((r) => (
            <div className="admin-row" key={r.id}>
              <span>
                <strong>{r.name || r.email}</strong>
                <small className="muted">{r.email}</small>
              </span>
              <span>{r.bet_count ?? 0}</span>
              <span>{r.has_stake_token ? 'Yes' : 'n/a'}</span>
              <span title={r.last_sync_message || ''}>{r.last_sync_status || 'n/a'}</span>
              <span>
                <button
                  type="button"
                  className="refresh-btn"
                  disabled={busy === r.id}
                  onClick={async () => {
                    setBusy(r.id)
                    try {
                      await revokeAdminSessions(r.id)
                      await load()
                    } catch (e) {
                      setErr(e?.message || 'Revoke failed')
                    } finally {
                      setBusy('')
                    }
                  }}
                >
                  {busy === r.id ? '…' : 'Revoke sessions'}
                </button>
              </span>
            </div>
          ))}
          {!rows.length && !err && <p className="muted">No accounts yet.</p>}
        </div>
      </section>
    </div>
  )
}
