import { useEffect, useState } from 'react'
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

/** Stake-style vertical bet ticket for a horizontal top-bets rail. */
export default function TopBetTicket({ bet, onOpenMatch }) {
  const { addLeg, setSlipMsg } = useBankroll()
  const [stake, setStake] = useState('')
  const odds = Number(bet.decimal_odds)
  const stakeNum = Number(stake)
  const payout = odds && stakeNum > 0 ? Math.round(stakeNum * odds) : null
  const tag = sportTag(bet.sport_key)

  const add = () => {
    const n = Number(stake)
    addLeg(legFromBet(bet, n > 0 ? n : null))
  }

  return (
    <article className={`bet-ticket-v ${bet.status === 'live' ? 'is-live' : ''}`}>
      <div className="bet-ticket-v-top">
        {tag && <span className="bet-ticket-v-sport">{tag}</span>}
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
        <small>{bet.market_name || bet.league || 'Match'}</small>
        <strong>{bet.label}</strong>
      </div>

      <div className="bet-ticket-v-odds">
        <span className="green">{fmtOdds(odds) || '-'}</span>
      </div>

      <div className="bet-ticket-v-stake">
        <label className="slip-amount">
          <span className="slip-amount-label">Amount</span>
          <input
            type="text"
            inputMode="decimal"
            placeholder=""
            value={stake}
            onChange={(e) => setStake(e.target.value.replace(/[^\d.]/g, ''))}
            aria-label="Amount"
          />
        </label>
        <div className="bet-ticket-v-payout">
          <span>Payout</span>
          <strong>{payout != null ? formatINR(payout) : 'n/a'}</strong>
        </div>
      </div>

      {(bet.handle_usd || bet.bettors || bet.books) && (
        <p className="bet-ticket-v-meta muted">
          {bet.handle_usd ? `${formatHandle(bet.handle_usd)} handle` : ''}
          {bet.bettors ? `${bet.handle_usd ? ' · ' : ''}${Number(bet.bettors).toLocaleString()} bettors` : ''}
          {!bet.handle_usd && bet.books ? `${bet.books} books` : ''}
        </p>
      )}

      <button type="button" className="btn-primary bet-ticket-v-add" onClick={add}>
        Add to slip
      </button>
    </article>
  )
}
