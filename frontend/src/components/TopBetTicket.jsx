import { useState } from 'react'
import TeamLogo from './TeamLogo'
import { useBankroll, formatINR } from '../context/BankrollContext'
import { fmtOdds } from './BoardBits'
import { legFromBet } from '../lib/slipRules'

function formatHandle(n) {
  if (n == null || !Number(n)) return null
  const v = Number(n)
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}k`
  return `$${Math.round(v)}`
}

function sportTag(key) {
  if (!key) return null
  if (key.startsWith('basket')) return 'Basketball'
  if (key.startsWith('cricket')) return 'Cricket'
  return 'Soccer'
}

function sourceLabel(src) {
  if (!src) return ''
  if (src.includes('stake')) return 'Stake odds'
  if (src.includes('skip')) return 'SkipOdds'
  if (src.includes('espn')) return 'ESPN odds'
  if (src.includes('double')) return 'Hot double'
  return ''
}

/** Stake-style vertical bet ticket - add without amount; payout only when amount set. */
export default function TopBetTicket({ bet, onOpenMatch }) {
  const { addLeg, setSlipMsg, setSlipOpen } = useBankroll()
  const [stake, setStake] = useState('')
  const odds = Number(bet.decimal_odds)
  const stakeNum = Number(stake)
  const payout = odds && stakeNum > 0 ? Math.round(stakeNum * odds) : null
  const tag = sportTag(bet.sport_key)
  const isCombo = bet.ticket_kind === 'combo' || bet.market === 'stake_combo'
  const comboParts = (bet.legs || []).map((l) => String(l.label || '').replace(/[—–]/g, ' - ')).filter(Boolean)
  const marketLabel = String(bet.market_name || (isCombo ? 'Combo' : 'Match Result'))
    .replace(/[—–]/g, ' - ')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
  const pickLabel = String(bet.label || '').replace(/[—–]/g, ' - ')

  const add = () => {
    const n = Number(stake)
    const ok = addLeg(legFromBet({
      ...bet,
      label: pickLabel,
      market: bet.market || (isCombo ? 'stake_combo' : 'match_winner'),
      market_name: marketLabel,
    }, n > 0 ? n : null))
    if (ok) setSlipOpen?.(true)
  }

  return (
    <article className={`bet-ticket-v ${bet.status === 'live' ? 'is-live' : ''} ${isCombo ? 'is-combo' : ''}`}>
      <div className="bet-ticket-v-top">
        {tag && <span className="bet-ticket-v-sport">{tag}</span>}
        {isCombo && <span className="bet-ticket-v-kind">Combo</span>}
        {bet.status === 'live' && <span className="live-tag">LIVE</span>}
      </div>

      <button
        type="button"
        className="bet-ticket-v-match"
        onClick={() => {
          setSlipMsg(null)
          onOpenMatch?.(bet)
        }}
      >
        <div className="bet-ticket-v-side">
          <TeamLogo name={bet.home_team} src={bet.home_logo} size={32} />
          <span>{bet.home_team}</span>
        </div>
        <div className="bet-ticket-v-side">
          <TeamLogo name={bet.away_team} src={bet.away_logo} size={32} />
          <span>{bet.away_team}</span>
        </div>
      </button>

      <div className="bet-ticket-v-pick">
        <small>{marketLabel || bet.league || 'Match'}</small>
        <strong>{pickLabel}</strong>
        {comboParts.length > 1 && (
          <ul className="bet-ticket-v-legs">
            {comboParts.map((p) => <li key={p}>{p}</li>)}
          </ul>
        )}
      </div>

      <div className="bet-ticket-v-odds">
        <span className="green">{fmtOdds(odds) || '-'}</span>
      </div>

      <div className="bet-ticket-v-stake">
        <label className="slip-amount">
          <span className="slip-amount-label">Amount (optional)</span>
          <input
            type="text"
            inputMode="decimal"
            placeholder="₹"
            value={stake}
            onChange={(e) => setStake(e.target.value.replace(/[^\d.]/g, ''))}
            aria-label="Amount"
          />
        </label>
        {payout != null && (
          <div className="bet-ticket-v-payout">
            <span>Payout</span>
            <strong>{formatINR(payout)}</strong>
          </div>
        )}
      </div>

      <p className="bet-ticket-v-meta muted">
        {bet.handle_usd ? `${formatHandle(bet.handle_usd)} handle` : ''}
        {bet.bettors ? `${bet.handle_usd ? ' · ' : ''}${Number(bet.bettors).toLocaleString()} bettors` : ''}
        {bet.books > 1 ? `${bet.handle_usd || bet.bettors ? ' · ' : ''}Tracked at ${bet.books} books` : ''}
        {!bet.handle_usd && !bet.bettors && bet.source ? sourceLabel(bet.source) : ''}
      </p>

      <button type="button" className="btn-primary bet-ticket-v-add" onClick={add}>
        Add to slip
      </button>
    </article>
  )
}
