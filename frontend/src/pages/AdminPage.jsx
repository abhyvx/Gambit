import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { fetchAdminAccounts, revokeAdminSessions } from '../api'
import { useEntryReady } from '../components/EntryScreen'
import './pages.css'

export default function AdminPage() {
  useEntryReady()
  const { user, openAuth } = useAuth()
  const [rows, setRows] = useState([])
  const [oddsLink, setOddsLink] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')

  const load = async () => {
    setErr('')
    try {
      const data = await fetchAdminAccounts()
      setRows(data?.accounts || [])
      setOddsLink(data?.odds_link || null)
    } catch (e) {
      setErr(e?.message || 'Admin access denied.')
      setRows([])
    }
  }

  useEffect(() => {
    if (user?.is_admin) load()
  }, [user?.is_admin])

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
          <h1>Admin</h1>
          <p className="subtitle">
            Account roster only. Stake tokens stay sealed per user — never shown here.
          </p>
        </div>
        <button type="button" className="refresh-btn" onClick={load}>Refresh</button>
      </header>

      <section className="panel">
        <h2 className="panel-title">Odds link</h2>
        <p className="muted">
          {oddsLink?.online
            ? `Online · last seen ${oddsLink.age_s != null ? `${Math.round(oddsLink.age_s / 60)}m ago` : oddsLink.at}`
            : oddsLink?.at
              ? `Offline · last seen ${oddsLink.at}`
              : 'No heartbeat yet — laptop relay has not checked in.'}
        </p>
      </section>

      <section className="panel">
        <h2 className="panel-title">Accounts ({rows.length})</h2>
        {err && <p className="muted" role="alert">{err}</p>}
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
              <span>{r.has_stake_token ? 'Yes' : '—'}</span>
              <span title={r.last_sync_message || ''}>{r.last_sync_status || '—'}</span>
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
