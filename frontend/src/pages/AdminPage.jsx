import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { fetchAdminAccounts, revokeAdminSessions } from '../api'
import { useEntryReady } from '../components/EntryScreen'
import './pages.css'

function fmtBool(v) {
  return v ? 'Yes' : 'No'
}

function fmtAt(v) {
  if (!v) return '—'
  try {
    return new Date(v).toLocaleString()
  } catch {
    return String(v)
  }
}

export default function AdminPage() {
  useEntryReady()
  const { user, openAuth } = useAuth()
  const [rows, setRows] = useState([])
  const [oddsLink, setOddsLink] = useState(null)
  const [debug, setDebug] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')

  const load = async () => {
    setErr('')
    try {
      const data = await fetchAdminAccounts()
      setRows(data?.accounts || [])
      setOddsLink(data?.odds_link || null)
      setDebug(data?.admin_debug || null)
    } catch (e) {
      setErr(e?.message || 'Admin access denied.')
      setRows([])
      setDebug(null)
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

  const stake = debug?.stake || {}
  const browser = stake?.browser || {}
  const overlay = stake?.overlay || {}
  const syncJobs = stake?.sync_jobs || {}
  const model = debug?.model || {}
  const craft = debug?.craft || {}
  const users = debug?.users || {}
  const bundle = debug?.bundle || {}
  const database = debug?.database || {}
  const security = debug?.security || {}

  return (
    <div className="page admin-page">
      <header className="page-header">
        <div>
          <h1>Admin</h1>
          <p className="subtitle">
            Full debug only for admins. Stake tokens stay sealed per user and are never shown here.
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
        <h2 className="panel-title">Live odds / browser debug</h2>
        <div className="admin-debug-grid">
          <article className="admin-debug-card">
            <h3>Stake mode</h3>
            <ul className="admin-debug-list">
              <li>Remote enabled: <strong>{fmtBool(stake.remote_enabled)}</strong></li>
              <li>Browserbase configured: <strong>{fmtBool(stake.browserbase_configured)}</strong></li>
              <li>Raw CDP configured: <strong>{fmtBool(stake.cdp_configured)}</strong></li>
              <li>Local browser enabled: <strong>{fmtBool(stake.local_browser_enabled)}</strong></li>
              <li>Startup warmup: <strong>{fmtBool(stake.warmup_on_startup)}</strong></li>
              <li>Odds loop: <strong>{stake.odds_loop_seconds || 0}s</strong></li>
            </ul>
            <p className="muted">
              If Remote enabled is Yes, live odds should use the cloud browser path instead of popping a local Stake window.
            </p>
          </article>

          <article className="admin-debug-card">
            <h3>Browser session</h3>
            <ul className="admin-debug-list">
              <li>Ready: <strong>{fmtBool(browser.ready)}</strong></li>
              <li>Warming: <strong>{fmtBool(browser.warming)}</strong></li>
              <li>Remote session: <strong>{fmtBool(browser.remote)}</strong></li>
              <li>Auth token captured: <strong>{fmtBool(browser.have_auth_token)}</strong></li>
              <li>Last error: <strong>{browser.last_error || '—'}</strong></li>
            </ul>
            {browser.login_url && (
              <a className="refresh-btn" href={browser.login_url} target="_blank" rel="noreferrer">
                Open remote Stake live view
              </a>
            )}
          </article>

          <article className="admin-debug-card">
            <h3>Overlay / relay</h3>
            <ul className="admin-debug-list">
              <li>Overlay data: <strong>{fmtBool(overlay.have_data)}</strong></li>
              <li>Fixtures priced: <strong>{overlay.fixtures ?? 0}</strong></li>
              <li>Cached overlays: <strong>{overlay.cached_overlays ?? 0}</strong></li>
              <li>Cooling down: <strong>{fmtBool(overlay.cooling_down)}</strong></li>
              <li>Fetching now: <strong>{fmtBool(overlay.fetching)}</strong></li>
              <li>Relay online: <strong>{fmtBool(stake.relay?.online)}</strong></li>
            </ul>
          </article>

          <article className="admin-debug-card">
            <h3>Sync queue</h3>
            <ul className="admin-debug-list">
              <li>Pending jobs: <strong>{syncJobs.pending ?? 0}</strong></li>
              <li>Recent jobs: <strong>{(syncJobs.recent || []).length}</strong></li>
            </ul>
            <div className="admin-chip-row">
              {(syncJobs.recent || []).slice(0, 6).map((job) => (
                <span key={job.id} className={`portfolio-pill ${job.status === 'error' ? 'result-lost' : job.status === 'pending' ? 'warn' : 'ok'}`}>
                  {job.status || 'unknown'}
                </span>
              ))}
              {!syncJobs.recent?.length && <span className="muted">No recent jobs.</span>}
            </div>
          </article>
        </div>
      </section>

      <section className="panel">
        <h2 className="panel-title">Users / persistence</h2>
        <div className="admin-debug-grid">
          <article className="admin-debug-card">
            <h3>Users</h3>
            <ul className="admin-debug-list">
              <li>Accounts: <strong>{users.accounts ?? rows.length}</strong></li>
              <li>Accounts with Stake token: <strong>{users.with_stake_token ?? 0}</strong></li>
              <li>Total imported bets: <strong>{users.bets_total ?? 0}</strong></li>
              <li>Active sessions: <strong>{users.active_sessions ?? 0}</strong></li>
            </ul>
          </article>
          <article className="admin-debug-card">
            <h3>Persistence bundle</h3>
            <ul className="admin-debug-list">
              <li>Bundle exists: <strong>{fmtBool(bundle.exists)}</strong></li>
              <li>Users persisted: <strong>{bundle.users ?? 0}</strong></li>
              <li>Portfolios persisted: <strong>{bundle.portfolios ?? 0}</strong></li>
              <li>Path: <strong className="mono">{bundle.path || '—'}</strong></li>
            </ul>
          </article>
          <article className="admin-debug-card">
            <h3>Database status</h3>
            <ul className="admin-debug-list">
              <li>Configured: <strong>{fmtBool(database.configured)}</strong></li>
              <li>Mode: <strong>{database.mode || 'filesystem'}</strong></li>
              <li>Driver: <strong>{database.driver || '—'}</strong></li>
            </ul>
            <p className="muted">{database.note || 'No database status reported yet.'}</p>
          </article>
          <article className="admin-debug-card">
            <h3>Admin security</h3>
            <ul className="admin-debug-list">
              <li>Admin email count: <strong>{security.admin_email_count ?? 0}</strong></li>
              <li>Shared admin secret enabled: <strong>{fmtBool(security.admin_secret_enabled)}</strong></li>
            </ul>
          </article>
        </div>
      </section>

      <section className="panel">
        <h2 className="panel-title">Model / craft debug</h2>
        <div className="admin-debug-grid">
          <article className="admin-debug-card">
            <h3>Model state</h3>
            <ul className="admin-debug-list">
              <li>Trained on: <strong>{model.trained_on ?? 0}</strong></li>
              <li>History corpus: <strong>{model.trained_on_history ?? 0}</strong></li>
              <li>Updated: <strong>{fmtAt(model.updated_at)}</strong></li>
            </ul>
            <div className="admin-chip-row">
              {Object.entries(model.trained_on_sport_history || {}).map(([sport, count]) => (
                <span key={sport} className="portfolio-pill ok">{sport}: {count}</span>
              ))}
            </div>
          </article>
          <article className="admin-debug-card">
            <h3>Craft status</h3>
            <ul className="admin-debug-list">
              <li>State: <strong>{craft.train_status?.state || '—'}</strong></li>
              <li>Epoch: <strong>{craft.train_status?.epoch ?? craft.latest?.epoch ?? '—'}</strong></li>
              <li>Latest ROI: <strong>{craft.latest?.roi ?? '—'}</strong></li>
              <li>Latest accuracy: <strong>{craft.latest?.accuracy ?? '—'}</strong></li>
              <li>Total epochs: <strong>{craft.epochs ?? 0}</strong></li>
            </ul>
          </article>
        </div>
        <div className="admin-log-list">
          {(model.activity_log || []).map((row, idx) => (
            <div className="admin-log-row" key={`${row.at || idx}-${row.kind || idx}`}>
              <div>
                <strong>{row.kind || 'event'}</strong>
                <small className="muted">{fmtAt(row.at)}</small>
              </div>
              <p>{row.message || '—'}</p>
            </div>
          ))}
          {!model.activity_log?.length && <p className="muted">No recent model activity.</p>}
        </div>
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
