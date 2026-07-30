import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import {
  fetchAdminAccounts,
  fetchLaptopSyncStatus,
  requeueFailedSyncJobs,
  requestLaptopOddsSync,
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

function fmtPct(v) {
  if (v == null || v === '' || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  // Desk ROI/accuracy are fractions (0.25 = 25%)
  const pct = Math.abs(n) <= 1.5 ? n * 100 : n
  return `${pct >= 0 ? '' : ''}${pct.toFixed(1)}%`
}

function activityLabel(kind) {
  const k = String(kind || 'event')
  if (k === 'train_complete') return 'Retrain'
  if (k === 'rec_grade') return 'Graded recs'
  if (k === 'desk_train') return 'Desk train'
  return k.replace(/_/g, ' ')
}

export default function AdminPage() {
  useEntryReady()
  const { user, ready, openAuth } = useAuth()
  const [oddsLink, setOddsLink] = useState(null)
  const [debug, setDebug] = useState(null)
  const [syncStatus, setSyncStatus] = useState(null)
  const [err, setErr] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState('')

  const load = async () => {
    setErr('')
    try {
      const data = await fetchAdminAccounts()
      setOddsLink(data?.odds_link || null)
      setDebug(data?.admin_debug || null)
      try {
        setSyncStatus(await fetchLaptopSyncStatus())
      } catch {
        setSyncStatus(null)
      }
    } catch (e) {
      setErr(e?.message || 'Admin access denied.')
      setDebug(null)
    }
  }

  useEffect(() => {
    if (user?.is_admin) load()
  }, [user?.is_admin])

  // Poll while a laptop odds request is pending
  useEffect(() => {
    if (!user?.is_admin || syncStatus?.status !== 'pending') return undefined
    const id = setInterval(async () => {
      try {
        const next = await fetchLaptopSyncStatus()
        setSyncStatus(next)
        if (next?.status === 'confirmed') {
          setNote(
            `Confirmed: laptop pushed ${next.fixtures ?? 'odds'} fixture(s) at ${fmtAt(next.confirmed_at)}.`
          )
          load()
        }
      } catch {
        /* ignore */
      }
    }, 4000)
    return () => clearInterval(id)
  }, [user?.is_admin, syncStatus?.status])

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
            Debug + laptop Stake sync. Stake tokens stay sealed.
          </p>
        </div>
        <button type="button" className="refresh-btn" onClick={load}>Refresh</button>
      </header>

      <nav className="admin-nav" aria-label="Admin sections">
        <Link className="admin-nav-link is-active" to="/app/admin">Overview</Link>
        <Link className="admin-nav-link" to="/app/admin/users">Users</Link>
      </nav>

      {(err || note) && (
        <p className="muted" role={err ? 'alert' : 'status'}>
          {err || note}
        </p>
      )}

      {!!patchNotes.length && (
        <section className="panel" aria-label="Latest patch">
          <h2 className="panel-title">Latest patch · {patchNotes[0].version}</h2>
          <p className="muted">{patchNotes[0].title}</p>
          <ul>
            {(patchNotes[0].changes || []).slice(0, 3).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <p className="muted" style={{ marginTop: '0.5rem' }}>
            <a href="#admin-patch-notes">Full patch notes ↓</a>
          </p>
        </section>
      )}

      <section className="panel">
        <h2 className="panel-title">Laptop Stake sync</h2>
        <p className="muted">
          {oddsLink?.online
            ? `Relay online · last seen ${oddsLink.age_s != null ? `${Math.round(oddsLink.age_s / 60)}m ago` : oddsLink.at}`
            : oddsLink?.at
              ? `Relay offline · last seen ${oddsLink.at}`
              : 'No laptop heartbeat yet. Run ./scripts/start_stake_relay.sh locally.'}
        </p>
        {syncStatus?.status && syncStatus.status !== 'idle' && (
          <p className={`portfolio-status ${syncStatus.status === 'confirmed' ? 'ok' : ''}`} role="status">
            Request {syncStatus.status}
            {syncStatus.requested_at ? ` · asked ${fmtAt(syncStatus.requested_at)}` : ''}
            {syncStatus.status === 'confirmed' && syncStatus.fixtures != null
              ? ` · ${syncStatus.fixtures} fixtures`
              : ''}
            {syncStatus.status === 'pending' ? ' · waiting for laptop relay push…' : ''}
          </p>
        )}
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
                setSyncStatus({
                  id: out?.id,
                  status: out?.status || 'pending',
                  requested_at: out?.requested_at,
                  open_url: out?.open_url || 'https://stake.com/',
                })
                if (out?.open_url) {
                  window.open(out.open_url, '_blank', 'noopener,noreferrer')
                }
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
          <a className="refresh-btn" href="https://stake.com/" target="_blank" rel="noreferrer">
            Open Stake.com
          </a>
        </div>
        <p className="muted" style={{ marginTop: '0.75rem' }}>
          Request opens Stake and flags the cloud. Confirmation appears after your laptop relay POSTs odds.
        </p>
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
              <li><span>Accounts</span><strong>{users.accounts ?? 0}</strong></li>
              <li><span>With Stake token</span><strong>{users.with_stake_token ?? 0}</strong></li>
              <li><span>Total bets</span><strong>{users.bets_total ?? 0}</strong></li>
              <li><span>Active sessions</span><strong>{users.active_sessions ?? 0}</strong></li>
            </ul>
            <p className="muted" style={{ marginTop: '0.75rem' }}>
              <Link to="/app/admin/users">Open users dashboard →</Link>
            </p>
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
        <p className="muted" style={{ marginBottom: '0.75rem' }}>
          Desk craft = frozen holdout training (same numbers as the Model page). Internal board paper-book runs are hidden.
        </p>
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
            <h3>Desk craft</h3>
            <ul className="admin-debug-list">
              <li><span>State</span><strong>{craft.train_status?.state || 'n/a'}</strong></li>
              <li><span>Epoch</span><strong>{craft.train_status?.epoch ?? craft.latest?.epoch ?? craft.epochs ?? '—'}</strong></li>
              <li>
                <span>Desk ROI</span>
                <strong>{fmtPct(craft.display_roi ?? craft.latest?.roi ?? craft.best?.roi)}</strong>
              </li>
              <li>
                <span>Desk accuracy</span>
                <strong>{fmtPct(craft.display_accuracy ?? craft.latest?.accuracy ?? craft.best?.accuracy)}</strong>
              </li>
              <li><span>Total epochs</span><strong>{Array.isArray(craft.epochs) ? craft.epochs.length : (craft.epochs ?? 0)}</strong></li>
              <li><span>Craft blocks</span><strong>{Array.isArray(craft.blocks) ? craft.blocks.length : (craft.blocks ?? 0)}</strong></li>
              {craft.best?.roi != null && (
                <li><span>Best ROI</span><strong>{fmtPct(craft.best.roi)}</strong></li>
              )}
              {craft.error ? <li><span>Craft debug</span><strong>{craft.error}</strong></li> : null}
            </ul>
          </article>
        </div>
        <div className="admin-log-list" style={{ marginTop: '0.9rem' }}>
          {(model.activity_log || [])
            .filter((row) => !['paper_craft', 'paper_book', 'gem_craft'].includes(String(row.kind || '')))
            .map((row, idx) => (
            <div className="admin-log-row" key={`${row.at || idx}-${row.kind || idx}`}>
              <div>
                <strong>{activityLabel(row.kind)}</strong>
                <small className="muted">{fmtAt(row.at)}</small>
              </div>
              <p>{row.message || 'n/a'}</p>
            </div>
          ))}
          {!model.activity_log?.filter((row) => !['paper_craft', 'paper_book', 'gem_craft'].includes(String(row.kind || ''))).length && (
            <p className="muted">No recent model activity.</p>
          )}
        </div>
      </section>

      <section className="panel" id="admin-patch-notes">
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
    </div>
  )
}
