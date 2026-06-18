import { useEffect, useState } from 'react'
import { fetchModelReport } from '../api'
import './pages.css'

function pct(x) { return x == null ? '—' : `${Math.round(x)}%` }

export default function ModelPage() {
  const [rep, setRep] = useState(null)
  const [loading, setLoading] = useState(true)
  const [retraining, setRetraining] = useState(false)
  const [err, setErr] = useState(null)

  const load = (retrain = false) => {
    if (retrain) setRetraining(true); else setLoading(true)
    setErr(null)
    fetchModelReport({ retrain })
      .then((r) => setRep(r))
      .catch((e) => setErr(String(e)))
      .finally(() => { setLoading(false); setRetraining(false) })
  }
  useEffect(() => { load(false) }, [])

  if (loading) return <div className="page"><p className="muted">Loading the model's report card…</p></div>
  if (err) return <div className="page"><p className="muted">Couldn't load the model report: {err}</p></div>

  const m = rep?.metrics || {}
  const corr = rep?.corrections || {}
  const topTeams = corr.top_teams || []
  const nHist = rep?.trained_on_history || 0
  const nWC = rep?.trained_on_worldcup || 0
  const fmt = (n) => (n == null ? '—' : n.toLocaleString())

  return (
    <div className="page model-page">
      <header className="simple-hero fade-up">
        <span className="page-eyebrow">🧠 SELF-LEARNING ENGINE</span>
        <h1>Model report card</h1>
        <p className="subtitle">
          The model learns team strength (Elo) and its goal model from <strong>{fmt(nHist)}</strong> real
          international matches, then grades itself against every finished World Cup game and rewrites
          its own calibration. Trained on <strong>{fmt(rep.trained_on)}</strong> games total.
        </p>
        <button className="retrain-btn" onClick={() => load(true)} disabled={retraining}>
          {retraining ? 'Re-learning…' : '↻ Re-learn from latest results'}
        </button>
      </header>

      {/* headline metrics */}
      <section className="model-stats">
        <div className="mstat">
          <span className="mstat-label">Out-of-sample accuracy</span>
          <strong className="mstat-val">{pct((m.holdout_accuracy ?? m.top_pick_accuracy ?? 0) * 100)}</strong>
          <small>on {fmt(m.holdout_n)} games it NEVER trained on (2021→today)</small>
        </div>
        <div className="mstat">
          <span className="mstat-label">Brier score (lower = sharper)</span>
          <strong className="mstat-val">{m.result_brier ?? '—'}</strong>
          <small>0.17 is strong for match-result prediction</small>
        </div>
        <div className="mstat">
          <span className="mstat-label">World Cup calls so far</span>
          <strong className="mstat-val">{pct((m.worldcup_accuracy || 0) * 100)}</strong>
          <small>{nWC} finished games this tournament</small>
        </div>
      </section>

      {/* the real story: accuracy WHEN confident */}
      {rep.confident && Object.keys(rep.confident).length > 0 && (
        <section className="guide-section">
          <h2>💎 When we're confident, we're right</h2>
          <p className="subtitle" style={{ marginTop: 0 }}>
            Three-way football has a hard ceiling near ~60% because draws are coin-flips. So the number
            that matters isn't the average — it's how often we're right <em>on the games we actually flag</em>.
            These are out-of-sample hit-rates on 2021→today.
          </p>
          <div className="conf-board">
            {[['55', 'Slight lean'], ['60', 'Confident'], ['65', 'Strong'], ['70', 'Lock']].map(([k, lbl]) => {
              const c = rep.confident[k]
              if (!c) return null
              return (
                <div key={k} className={`conf-tile tier-${k}`}>
                  <span className="conf-thr">top pick ≥{k}%</span>
                  <strong className="conf-acc">{pct(c.accuracy * 100)}</strong>
                  <span className="conf-lbl">{lbl}</span>
                  <small>right, over {fmt(c.n)} games</small>
                </div>
              )
            })}
          </div>
          <p className="muted" style={{ marginTop: '12px' }}>
            That's why the matches page tags <strong>high-confidence spots</strong> — those are the ones to actually bet.
          </p>
        </section>
      )}

      {/* what it learned */}
      <section className="guide-section">
        <h2>🔎 What it learned</h2>
        <ul className="model-diagnosis">
          {(rep.diagnosis || []).map((d, i) => <li key={i}>{d}</li>)}
        </ul>
        <div className="model-corrections">
          <div className="corr-chip">
            <span>Training data</span>
            <strong>{fmt(nHist)}</strong>
            <small>real international matches replayed</small>
          </div>
          <div className="corr-chip">
            <span>Outcomes graded</span>
            <strong>{fmt(m.n_outcomes_graded)}</strong>
            <small>predictions checked vs reality</small>
          </div>
          <div className="corr-chip">
            <span>Confidence calibration</span>
            <strong>{(corr.calibration?.result?.a ?? 1).toFixed(2)}×</strong>
            <small>{(corr.calibration?.result?.a ?? 1) < 0.97 ? 'softening over-confidence'
              : (corr.calibration?.result?.a ?? 1) > 1.03 ? 'sharpening' : 'already well calibrated'}</small>
          </div>
        </div>
      </section>

      {/* learned team strength */}
      {topTeams.length > 0 && (
        <section className="guide-section">
          <h2>🏆 Learned team strength (Elo)</h2>
          <p className="subtitle" style={{ marginTop: 0 }}>
            Computed purely from real results — recent games move a rating most. This is what actually
            drives every win/draw/loss probability, not reputation.
          </p>
          <div className="elo-board">
            {topTeams.slice(0, 16).map((t, i) => (
              <div key={i} className="elo-row">
                <span className="elo-rank">{i + 1}</span>
                <span className="elo-team">{t.team.replace(/\b\w/g, (c) => c.toUpperCase())}</span>
                <span className="elo-val">{Math.round(t.elo)}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* reliability curve */}
      <section className="guide-section">
        <h2>🎯 Is "70%" really 70%? (calibration)</h2>
        <p className="subtitle" style={{ marginTop: 0 }}>
          Each bar compares what the model <em>said</em> would happen against what <em>actually</em> happened.
          Closer together = more trustworthy probabilities.
        </p>
        <div className="reliability">
          {(rep.reliability || []).map((b, i) => (
            <div key={i} className="rel-row">
              <span className="rel-range">{b.range}</span>
              <div className="rel-bars">
                <div className="rel-bar pred" style={{ width: `${b.predicted}%` }}><span>{b.predicted}% said</span></div>
                <div className="rel-bar act" style={{ width: `${b.actual}%` }}><span>{b.actual}% real</span></div>
              </div>
              <span className="rel-n">n={b.n}</span>
            </div>
          ))}
        </div>
      </section>

      {/* recent calls */}
      <section className="guide-section">
        <h2>📋 Recent calls vs reality</h2>
        <div className="recent-calls">
          {(rep.recent || []).map((r, i) => (
            <div key={i} className={`call ${r.top_pick_hit ? 'hit' : 'miss'}`}>
              <div className="call-match">{r.match}</div>
              <div className="call-meta">
                <span>called <strong>{r.top_pick}</strong> ({pct(r.top_pick_p * 100)})</span>
                <span className="call-tot">pred {r.pred_total} / actual {r.actual_total} goals</span>
              </div>
              <span className={`call-badge ${r.top_pick_hit ? 'hit' : 'miss'}`}>{r.top_pick_hit ? '✓ right' : '✗ wrong'}</span>
            </div>
          ))}
        </div>
      </section>

      <p className="math-note">
        Self-learning means the model improves as more games finish — corrections are bounded so a small
        sample can't make it swing wildly. This is analytical software, not a guarantee.
      </p>
    </div>
  )
}
