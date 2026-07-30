import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import {
  fetchAdminAccounts,
  requeueFailedSyncJobs,
  requestLaptopOddsSync,
  revokeAdminSessions,
} from '../api'
import { useEntryReady } from '../components/EntryScreen'
import './pages.css'

function fmtBool(v) {
  return v ? 'Yes' : 'No'
}

function fmtAt(v) {
  if (!v) return 'n/a'
  try {
    return new Date(v).toLocaleString()
  } catch {
    return String(v)
  }
}

export default function AdminPage() {
  useEntryReady()
  const { user, ready, openAuth } = useAuth()
  const [rows, setRows] = useState([])
  const [oddsLink, setOddsLink] = useState(null)
  const [debug, setDebug] = useState(null)
  const [err, setErr] = useState('')
  const [note, setNote] = useState('')
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

  if (!ready) {
    return (
      <div className="page">
        <p className="muted">Loading account…</p>
      </div>
    )
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
  const patchNotes = debug?.patch_notes || []

  return (
    <div className="page admin-page">
      <header className="page-header">
        <div>
          <h1>Admin</h1>
          <p className="subtitle">
            Debug + patch notes. Stake tokens stay sealed and are never shown here.
          </p>
        </div>
        <button type="button" className="refresh-btn" onClick={load}>Refresh</button>
      </header>

      {(err || note) && (
        <p className={`muted ${err ? '' : ''}`} role={err ? 'alert' : 'status'}>
          {err || note}
        </p>
      )}

      <section className="panel">
        <h2 className="panel-title">Patch notes</h2>
        <p className="muted">
          Version and debugging-cycle log — what broke, what we fixed. Newest first.
        </p>
        <div className="admin-patch-list">
          {patchNotes.map((entry) => (
            <article className="admin-patch-card" key={`${entry.version}-${entry.cycle}`}>
              <h3>{entry.title || entry.version}</h3>
              <div className="admin-patch-meta">
                <span>{entry.version}</span>
                <span>{entry.cycle}</span>
                <span>{entry.at || 'n/a'}</span>
              </div>
              {!!entry.fixed?.length && (
                <>
                  <p className="patch-label">Broken</p>
                  <ul>
                    {entry.fixed.map((line) => <li key={line}>{line}</li>)}
                  </ul>
                </>
              )}
              {!!entry.changes?.length && (
                <>
                  <p className="patch-label">Fixed / shipped</p>
                  <ul>
                    {entry.changes.map((line) => <li key={line}>{line}</li>)}
                  </ul>
                </>
              )}
            </article>
          ))}
          {!patchNotes.length && <p className="muted">No patch notes yet.</p>}
        </div>
      </section>

      <section className="panel">
        <h2 className="panel-title">Laptop Stake sync</h2>
        <p className="muted">
          {oddsLink?.online
            ? `Relay online · last seen ${oddsLink.age_s != null ? `${Math.round(oddsLink.age_s / 60)}m ago` : oddsLink.at}`
            : oddsLink?.at
              ? `Relay offline · last seen ${oddsLink.at}`
              : 'No laptop heartbeat yet. Run ./scripts/start_stake_relay.sh locally.'}
        </p>
        <div className="admin-actions">
          <button
            type="button"
            className="refresh-btn"
            disabled={busy === 'laptop'}
            onClick={async () => {
              setBusy('laptop')
              setErr('')
              setNote('')
              try {
                const out = await requestLaptopOddsSync()
                setNote(out?.message || 'Laptop odds sync requested.')
                await load()
              } catch (e) {
                setErr(e?.message || 'Laptop sync request failed.')
              } finally {
                setBusy('')
              }
            }}
          >
            {busy === 'laptop' ? 'Requesting…' : 'Request laptop odds sync'}
          </button>
          <button
            type="button"
            className="refresh-btn"
            disabled={busy === 'requeue'}
            onClick={async () => {
              setBusy('requeue')
              setErr('')
              setNote('')
              try {
                const out = await requeueFailedSyncJobs()
                setNote(`Re-queued ${out?.requeued ?? 0} failed import(s). Pending: ${out?.pending ?? 0}.`)
                await load()
              } catch (e) {
                setErr(e?.message || 'Requeue failed.')
              } finally {
                setBusy('')
              }
            }}
          >
            {busy === 'requeue' ? 'Re-queuing…' : 'Re-queue failed imports'}
          </button>
        </div>
      </section>

      <section className="panel">
        <h2 className="panel-title">Live odds / browser debug</h2>
        <div className="admin-debug-grid">
          <article className="admin-debug-card">
            <h3>Stake mode</h3>
            <ul className="admin-debug-list">
              <li><span>Remote enabled</span><strong>{fmtBool(stake.remote_enabled)}</strong></li>
              <li><span>Browserbase</span><strong>{fmtBool(stake.browserbase_configured)}</strong></li>
              <li><span>Raw CDP</span><strong>{fmtBool(stake.cdp_configured)}</strong></li>
              <li><span>Local browser</span><strong>{fmtBool(stake.local_browser_enabled)}</strong></li>
              <li><span>Startup warmup</span><strong>{fmtBool(stake.warmup_on_startup)}</strong></li>
              <li><span>Odds loop</span><strong>{stake.odds_loop_seconds || 0}s</strong></li>
            </ul>
            <p className="muted">
              Remote Yes means cloud browser path — no local Stake popup on Render.
            </p>
          </article>

          <article className="admin-debug-card">
            <h3>Browser session</h3>
            <ul className="admin-debug-list">
              <li><span>Ready</span><strong>{fmtBool(browser.ready)}</strong></li>
              <li><span>Warming</span><strong>{fmtBool(browser.warming)}</strong></li>
              <li><span>Remote session</span><strong>{fmtBool(browser.remote)}</strong></li>
              <li><span>Auth token</span><strong>{fmtBool(browser.have_auth_token)}</strong></li>
              <li><span>Last error</span><strong title={browser.last_error || ''}>{browser.last_error || 'n/a'}</strong></li>
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
              <li><span>Overlay data</span><strong>{fmtBool(overlay.have_data)}</strong></li>
              <li><span>Fixtures priced</span><strong>{overlay.fixtures ?? 0}</strong></li>
              <li><span>Cached overlays</span><strong>{overlay.cached_overlays ?? 0}</strong></li>
              <li><span>Cooling down</span><strong>{fmtBool(overlay.cooling_down)}</strong></li>
              <li><span>Fetching now</span><strong>{fmtBool(overlay.fetching)}</strong></li>
              <li><span>Relay online</span><strong>{fmtBool(stake.relay?.online)}</strong></li>
            </ul>
          </article>

          <article className="admin-debug-card">
            <h3>Sync queue</h3>
            <ul className="admin-debug-list">
              <li><span>Pending jobs</span><strong>{syncJobs.pending ?? 0}</strong></li>
              <li><span>Recent jobs</span><strong>{(syncJobs.recent || []).length}</strong></li>
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
              <li><span>Accounts</span><strong>{users.accounts ?? rows.length}</strong></li>
              <li><span>With Stake token</span><strong>{users.with_stake_token ?? 0}</strong></li>
              <li><span>Total bets</span><strong>{users.bets_total ?? 0}</strong></li>
              <li><span>Active sessions</span><strong>{users.active_sessions ?? 0}</strong></li>
            </ul>
          </article>
          <article className="admin-debug-card">
            <h3>Persistence bundle</h3>
            <ul className="admin-debug-list">
              <li><span>Bundle exists</span><strong>{fmtBool(bundle.exists)}</strong></li>
              <li><span>Users persisted</span><strong>{bundle.users ?? 0}</strong></li>
              <li><span>Portfolios</span><strong>{bundle.portfolios ?? 0}</strong></li>
              <li><span>Path</span><strong className="mono" title={bundle.path || ''}>{bundle.path || 'n/a'}</strong></li>
            </ul>
          </article>
          <article className="admin-debug-card">
            <h3>Database status</h3>
            <ul className="admin-debug-list">
              <li><span>Configured</span><strong>{fmtBool(database.configured)}</strong></li>
              <li><span>Mode</span><strong>{database.mode || 'filesystem'}</strong></li>
              <li><span>Driver</span><strong>{database.driver || 'n/a'}</strong></li>
            </ul>
            <p className="muted">{database.note || 'No database status reported yet.'}</p>
          </article>
          <article className="admin-debug-card">
            <h3>Admin security</h3>
            <ul className="admin-debug-list">
              <li><span>Admin email count</span><strong>{security.admin_email_count ?? 0}</strong></li>
              <li><span>Shared secret</span><strong>{fmtBool(security.admin_secret_enabled)}</strong></li>
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
              <li><span>Trained on</span><strong>{model.trained_on ?? 0}</strong></li>
              <li><span>History corpus</span><strong>{model.trained_on_history ?? 0}</strong></li>
              <li><span>Updated</span><strong>{fmtAt(model.updated_at)}</strong></li>
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
              <li><span>State</span><strong>{craft.train_status?.state || 'n/a'}</strong></li>
              <li><span>Epoch</span><strong>{craft.train_status?.epoch ?? craft.latest?.epoch ?? '—'}</strong></li>
              <li><span>Latest ROI</span><strong>{craft.latest?.roi ?? '—'}</strong></li>
              <li><span>Latest accuracy</span><strong>{craft.latest?.accuracy ?? '—'}</strong></li>
              <li><span>Total epochs</span><strong>{Array.isArray(craft.epochs) ? craft.epochs.length : (craft.epochs ?? 0)}</strong></li>
              <li><span>Craft blocks</span><strong>{Array.isArray(craft.blocks) ? craft.blocks.length : (craft.blocks ?? 0)}</strong></li>
              {craft.error ? <li><span>Craft debug</span><strong>{craft.error}</strong></li> : null}
            </ul>
          </article>
        </div>
        <div className="admin-log-list" style={{ marginTop: '0.9rem' }}>
          {(model.activity_log || []).map((row, idx) => (
            <div className="admin-log-row" key={`${row.at || idx}-${row.kind || idx}`}>
              <div>
                <strong>{row.kind || 'event'}</strong>
                <small className="muted">{fmtAt(row.at)}</small>
              </div>
              <p>{row.message || 'n/a'}</p>
            </div>
          ))}
          {!model.activity_log?.length && <p className="muted">No recent model activity.</p>}
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
