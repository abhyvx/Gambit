import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useBankroll, formatINR } from '../context/BankrollContext'
import { useAuth } from '../context/AuthContext'
import {
  fetchBettorStyleCatalog,
  disconnectPortfolioSession,
  authDeleteAccount,
} from '../api'
import { useEntryReady } from '../components/EntryScreen'
import './pages.css'

const FALLBACK_GOALS = [
  { id: 'preserve', label: 'Protect bankroll', blurb: 'Fewer, higher-probability bets. Skip more matches.' },
  { id: 'hit_target', label: 'Hit a cashout target', blurb: 'Size paths that can reach your ₹ goal.' },
  { id: 'value', label: 'Find edge / +EV', blurb: 'Chase mispriced odds even if win% is lower.' },
  { id: 'fun', label: 'Entertainment', blurb: 'Parlays and longer shots are fine. Still skip garbage.' },
]
const FALLBACK_RISKS = [
  { id: 'low', label: 'Low' },
  { id: 'medium', label: 'Medium' },
  { id: 'high', label: 'High' },
]
const FALLBACK_STRUCTURES = [
  { id: 'singles', label: 'One best bet' },
  { id: 'spread', label: 'Several singles' },
  { id: 'mixed', label: 'Singles + occasional combo' },
  { id: 'parlays', label: 'Parlays welcome' },
]

export default function SettingsPage() {
  useEntryReady()
  const {
    perMatchBudget, updatePerMatchBudget,
    targetCashout, updateTargetCashout,
    bettorStyle, updateBettorStyle, presets,
  } = useBankroll()
  const { user, openAuth, logout } = useAuth()
  const [budgetDraft, setBudgetDraft] = useState(String(perMatchBudget))
  const [cashoutDraft, setCashoutDraft] = useState(String(targetCashout))
  const [catalog, setCatalog] = useState(null)
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')

  useEffect(() => { setBudgetDraft(String(perMatchBudget)) }, [perMatchBudget])
  useEffect(() => { setCashoutDraft(String(targetCashout)) }, [targetCashout])
  useEffect(() => {
    fetchBettorStyleCatalog()
      .then((r) => setCatalog(r.catalog))
      .catch(() => setCatalog(null))
  }, [])

  const goals = catalog?.goals || FALLBACK_GOALS
  const risks = catalog?.risks || FALLBACK_RISKS
  const structures = catalog?.structures || FALLBACK_STRUCTURES

  const clearStake = async () => {
    setBusy('stake')
    setMsg('')
    try {
      await disconnectPortfolioSession()
      setMsg('Stake token cleared from this account.')
    } catch (e) {
      setMsg(e?.message || 'Could not clear Stake token.')
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
    <div className="page settings-page">
      <header className="page-header">
        <div>
          <h1>Account & settings</h1>
          <p className="subtitle">
            Profile, Stake connection, bankroll style, and legal docs.
          </p>
        </div>
      </header>

      <section className="panel">
        <h2 className="panel-title">Account</h2>
        {user ? (
          <div className="settings-account">
            <p><strong>{user.name || 'You'}</strong> · {user.email}</p>
            <div className="settings-actions">
              <button type="button" className="refresh-btn" onClick={logout}>Sign out</button>
              <button type="button" className="refresh-btn" disabled={busy === 'stake'} onClick={clearStake}>
                {busy === 'stake' ? 'Clearing…' : 'Remove Stake token'}
              </button>
              <button type="button" className="refresh-btn danger" disabled={busy === 'delete'} onClick={removeAccount}>
                {busy === 'delete' ? 'Deleting…' : 'Delete account'}
              </button>
            </div>
          </div>
        ) : (
          <div className="settings-account">
            <p className="muted">Sign in to keep your journal private and connect Stake with an API token.</p>
            <div className="settings-actions">
              <button type="button" className="refresh-btn" onClick={() => openAuth('login')}>Sign in</button>
              <button type="button" className="refresh-btn" onClick={() => openAuth('signup')}>Create account</button>
            </div>
          </div>
        )}
        {msg && <p className="muted" role="status">{msg}</p>}
        <p className="muted">
          Stake connect lives on <Link to="/app/portfolio">Portfolio</Link> (paste API token).
        </p>
      </section>

      <section className="panel">
        <h2 className="panel-title">Legal</h2>
        <div className="settings-actions">
          <Link className="refresh-btn" to="/app/legal/privacy">Privacy</Link>
          <Link className="refresh-btn" to="/app/legal/terms">Terms</Link>
        </div>
        <p className="responsible-note">
          18+ only · Analytics software, not a bookmaker · Bet only what you can afford to lose.
        </p>
      </section>

      <section className="panel">
        <h2 className="panel-title">What do you want?</h2>
        <p className="panel-desc">Goal, risk, and structure control which bets get surfaced.</p>
        <div className="style-grid">
          {goals.map((g) => (
            <button
              key={g.id}
              type="button"
              className={`style-card ${bettorStyle.goal === g.id ? 'active' : ''}`}
              onClick={() => updateBettorStyle({ goal: g.id })}
            >
              <strong>{g.label}</strong>
              <span>{g.blurb}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2 className="panel-title">Risk appetite</h2>
        <div className="preset-row">
          {risks.map((r) => (
            <button
              key={r.id}
              type="button"
              className={`preset-btn ${bettorStyle.risk === r.id ? 'active' : ''}`}
              onClick={() => updateBettorStyle({ risk: r.id })}
            >
              {r.label}
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2 className="panel-title">How do you like to place bets?</h2>
        <div className="style-grid">
          {structures.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`style-card ${bettorStyle.structure === s.id ? 'active' : ''}`}
              onClick={() => updateBettorStyle({ structure: s.id })}
            >
              <strong>{s.label}</strong>
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        <label htmlFor="budget-input">Max budget for a single match</label>
        <div className="money-field">
          <span>₹</span>
          <input
            id="budget-input"
            type="number"
            min={50}
            max={5000}
            value={budgetDraft}
            onChange={(e) => setBudgetDraft(e.target.value)}
            onBlur={() => updatePerMatchBudget(budgetDraft)}
            onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
          />
        </div>
        <div className="preset-row">
          {presets.map((p) => (
            <button
              key={p}
              type="button"
              className={`preset-btn ${Number(perMatchBudget) === p ? 'active' : ''}`}
              onClick={() => updatePerMatchBudget(p)}
            >
              {formatINR(p)}
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        <label htmlFor="cashout-input">Target cashout (for hit-target style)</label>
        <div className="money-field">
          <span>₹</span>
          <input
            id="cashout-input"
            type="number"
            min={100}
            max={100000}
            value={cashoutDraft}
            onChange={(e) => setCashoutDraft(e.target.value)}
            onBlur={() => updateTargetCashout(cashoutDraft)}
            onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
          />
        </div>
        <p className="muted">
          Used when your goal is “Hit a cashout target”. Required multiplier:{' '}
          <strong>{(targetCashout / Math.max(perMatchBudget, 1)).toFixed(1)}x</strong>
        </p>
      </section>
    </div>
  )
}
