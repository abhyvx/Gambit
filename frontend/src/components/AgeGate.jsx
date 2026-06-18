import { useEffect, useState } from 'react'

const KEY = 'gambit_age_ack_v1'

export default function AgeGate() {
  const [ack, setAck] = useState(true)

  useEffect(() => {
    try { setAck(localStorage.getItem(KEY) === '1') } catch { setAck(true) }
  }, [])

  if (ack) return null

  const accept = () => {
    try { localStorage.setItem(KEY, '1') } catch { /* ignore */ }
    setAck(true)
  }

  return (
    <div className="agegate-overlay" role="dialog" aria-modal="true" aria-label="Age verification">
      <div className="agegate-card">
        <div className="agegate-logo" aria-hidden>⚡</div>
        <h2>Before you continue</h2>
        <p>
          GAMBIT is an <strong>analytics tool</strong> for football betting markets — it is not a
          bookmaker and does not take bets or hold money. Predictions and "value" calls are
          informational opinions, <strong>not financial advice or a guarantee of any outcome</strong>.
        </p>
        <ul className="agegate-points">
          <li>You are <strong>18 or older</strong> (or the legal age where you live).</li>
          <li>Betting carries real risk — only ever stake what you can afford to lose.</li>
          <li>Gambling is restricted or illegal in some places; you're responsible for your local laws.</li>
        </ul>
        <button className="agegate-accept" onClick={accept}>I'm 18+ and I understand</button>
        <p className="agegate-help">
          Need support? Many regions offer free, confidential help (e.g. BeGambleAware, 1‑800‑GAMBLER).
        </p>
      </div>
    </div>
  )
}
