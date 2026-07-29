import { useEffect, useState } from 'react'
import { useBankroll, formatINR } from '../context/BankrollContext'
import { fetchBettorStyleCatalog } from '../api'
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
  const [budgetDraft, setBudgetDraft] = useState(String(perMatchBudget))
  const [cashoutDraft, setCashoutDraft] = useState(String(targetCashout))
  const [catalog, setCatalog] = useState(null)

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

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Style & bankroll</h1>
          <p className="subtitle">
            Goal, risk, and structure control which bets get surfaced. Change anytime.
          </p>
        </div>
      </header>

      <section className="panel">
        <h2 className="panel-title">What do you want?</h2>
        <p className="panel-desc">Pick a goal. Change anytime.</p>
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

      <p className="responsible-note">
        18+ only · Betting carries real risk of loss. Only bet money you can afford to lose.
      </p>
    </div>
  )
}
