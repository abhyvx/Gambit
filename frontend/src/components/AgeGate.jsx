import { useEffect, useState } from 'react'
import { GambitMark } from './GambitLogo'

const KEY = 'gambit_age_ack_v1'

export default function AgeGate() {
  const [ack, setAck] = useState(null)

  useEffect(() => {
    try { setAck(localStorage.getItem(KEY) === '1') } catch { setAck(false) }
  }, [])

  if (ack == null) return null
  if (ack) return null

  const accept = () => {
    try { localStorage.setItem(KEY, '1') } catch { /* ignore */ }
    setAck(true)
  }

  return (
    <div className="agegate-overlay" role="dialog" aria-modal="true" aria-label="Age verification">
      <div className="agegate-card">
        <div className="agegate-logo" aria-hidden><GambitMark size={48} /></div>
        <h2>Age check</h2>
        <p>
          GAMBIT is analytics software, not a bookmaker. Outputs are informational,
          not financial advice or a guarantee of profit.
        </p>
        <ul className="agegate-points">
          <li>You are <strong>18 or older</strong> (or the legal age where you live).</li>
          <li>Betting carries real risk. Only stake what you can afford to lose.</li>
          <li>Gambling is restricted or illegal in some places. You are responsible for your local laws.</li>
          <li>You place any bets yourself. Gambit never submits wagers for you.</li>
        </ul>
        <button className="agegate-accept" onClick={accept}>I am 18+ and I understand</button>
        <p className="agegate-help">
          By continuing you agree to the{' '}
          <a href="/app/legal/terms">Terms</a> and <a href="/app/legal/privacy">Privacy</a> notices.
          Need support? BeGambleAware, 1-800-GAMBLER, or local services.
        </p>
      </div>
    </div>
  )
}
