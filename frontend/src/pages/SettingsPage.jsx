import { useBankroll, formatINR } from '../context/BankrollContext'
import './pages.css'

export default function SettingsPage() {
  const { perMatchBudget, updatePerMatchBudget, presets } = useBankroll()

  return (
    <div className="page">
      <header className="simple-hero fade-up">
        <span className="page-eyebrow">💰 BANKROLL</span>
        <h1>Budget per match</h1>
        <p className="subtitle">
          How much you're willing to risk on <strong>one match only</strong> — not your whole wallet.
          Pocket money only; never bet rent, food, or tuition money.
        </p>
      </header>

      <section className="settings-card fade-up">
        <label htmlFor="budget-input">Max budget for a single match</label>
        <div className="budget-input-wrap">
          <span className="budget-currency">₹</span>
          <input
            id="budget-input"
            type="number"
            min={50}
            max={5000}
            value={perMatchBudget}
            onChange={(e) => updatePerMatchBudget(e.target.value)}
          />
        </div>

        <div className="preset-row">
          {presets.map((p) => (
            <button
              key={p}
              className={`preset-btn ${Number(perMatchBudget) === p ? 'active' : ''}`}
              onClick={() => updatePerMatchBudget(p)}
            >
              {formatINR(p)}
            </button>
          ))}
        </div>

        <div className="budget-breakdown">
          <div className="bb-item">
            <span>Typical single bet</span>
            <strong>up to {formatINR(perMatchBudget * 0.5)}</strong>
            <small>50% of match budget</small>
          </div>
          <div className="bb-item">
            <span>Optional parlay</span>
            <strong>up to {formatINR(perMatchBudget * 0.15)}</strong>
            <small>15% of match budget</small>
          </div>
        </div>
      </section>

      <section className="guide-section fade-up">
        <h2>Student rules</h2>
        <ol className="rules-ol">
          <li>₹200–₹500 per match is sensible for students.</li>
          <li>12 MD2 matches × ₹300 = ₹3,600 max if you bet every match (you should not).</li>
          <li><strong>SKIP MATCH</strong> = keep all {formatINR(perMatchBudget)} for that game.</li>
          <li>Parlays are fun but risky — only use leftover budget after singles.</li>
        </ol>
      </section>

      <p className="responsible-note">
        18+ only · Betting carries real risk of loss. If it stops being fun or starts costing more than you can afford,
        stop — and seek help if you need it.
      </p>
    </div>
  )
}
