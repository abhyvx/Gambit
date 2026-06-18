import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchWorldCup } from '../api/index'
import { useBankroll, formatINR } from '../context/BankrollContext'
import VerdictBadge from '../components/VerdictBadge'
import MatchSlipPanel from '../components/MatchSlipPanel'
import './pages.css'

const TABS = [
  { id: null, label: 'Today', sub: 'Live' },
  { id: 1, label: 'MD 1' },
  { id: 2, label: 'MD 2' },
  { id: 3, label: 'MD 3' },
  { id: 0, label: 'All games' },
]

function MatchCard({ m, expanded, onToggle, variant }) {
  const open = expanded === m.fixture_id
  const isLive = variant === 'live'
  const isDone = variant === 'completed'

  return (
    <article className={`wc-match-card ${isLive ? 'live-card' : ''} ${isDone ? 'completed-card' : ''} ${open ? 'is-open' : ''}`}>
      <header className="wc-match-header" onClick={() => onToggle(m.fixture_id)}>
        <div className="wc-match-info">
          <div className="wc-tag-row">
            {isLive && <span className="live-pill pulse">● LIVE</span>}
            {isDone && <span className="ft-pill">FULL TIME</span>}
            <span className="group-tag">{isDone ? `MD${m.matchday} · ` : ''}Group {m.group}</span>
            {!isLive && !isDone && m.odds_source && (
              <span className="odds-source-tag">
                {m.odds_source === 'espn_draftkings' ? '📊 DraftKings (live)' : m.odds_source}
              </span>
            )}
          </div>

          <div className="wc-teams">
            <span className="team">{m.home_team}</span>
            {isLive || isDone ? (
              <span className="score">{m.score}</span>
            ) : (
              <span className="vs">vs</span>
            )}
            <span className="team">{m.away_team}</span>
          </div>

          <div className="wc-meta-row">
            {isLive && m.status_detail && <span className="status-detail">{m.status_detail}</span>}
            {!isLive && !isDone && m.team_ratings && (
              <span className="rating-tag">⭐ {m.team_ratings.home} <span className="rating-vs">vs</span> {m.team_ratings.away}</span>
            )}
          </div>

          {!isDone && m.fan_prediction && (
            <p className="fan-preview">{m.fan_prediction.slice(0, 150)}…</p>
          )}
        </div>

        <div className="wc-match-aside">
          {!isLive && !isDone && <VerdictBadge verdict={m.bet_slip?.verdict || m.verdict?.verdict} />}
          <span className={`chevron ${open ? 'up' : ''}`} aria-hidden>⌄</span>
        </div>
      </header>

      {open && (
        <div className="wc-match-body">
          <MatchSlipPanel
            slip={m.bet_slip}
            home={m.home_team}
            away={m.away_team}
            fanPrediction={m.fan_prediction}
            status={m.status}
            score={m.score}
          />
        </div>
      )}
    </article>
  )
}

function MatchSkeleton() {
  return (
    <div className="wc-skeleton-card">
      <div className="skeleton sk-row sk-tags" />
      <div className="skeleton sk-row sk-title" />
      <div className="skeleton sk-row sk-meta" />
    </div>
  )
}

export default function WorldCupPage() {
  const { perMatchBudget } = useBankroll()
  const [data, setData] = useState(null)
  const [matchday, setMatchday] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)
  const [expanded, setExpanded] = useState(null)
  const [showFinished, setShowFinished] = useState(false)

  const load = (md, refresh = false) => {
    if (refresh) setRefreshing(true)
    else setLoading(true)
    setError(null)
    fetchWorldCup({
      matchday: md ?? undefined,
      budgetPerMatchInr: perMatchBudget,
      // Show full matchday slates (finished + live + upcoming), not just what's left to kick off
      includeCompleted: md === null || md === 0 || md === 1 || md === 2 || md === 3,
      forceRefresh: refresh,
    })
      .then(setData)
      .catch((e) => setError(e?.message || 'Could not reach the engine.'))
      .finally(() => {
        setLoading(false)
        setRefreshing(false)
      })
  }

  useEffect(() => {
    load(matchday)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchday, perMatchBudget])

  const toggle = (id) => setExpanded((cur) => (cur === id ? null : id))

  const live = data?.matches?.filter((m) => m.status === 'live') || []
  const upcoming = data?.matches?.filter((m) => m.status === 'upcoming') || []
  const completed = data?.matches?.filter((m) => m.status === 'completed') || []

  return (
    <div className="page page-wide">
      {/* ── Hero ── */}
      <header className="wc-hero fade-up">
        <div className="wc-hero-glow" aria-hidden />
        <div className="wc-hero-top">
          <div>
            <span className="wc-eyebrow">⚡ WORLD CUP 2026 · POWERED BY GAMBIT</span>
            <h1>Bet the World Cup like you have inside info</h1>
            <p className="wc-hero-sub">{data?.message || 'Real Stake odds, an honest read on every match, and the bets we\u2019d actually back — built to keep you from losing.'}</p>
          </div>
          <div className="wc-hero-stats">
            {live.length > 0 && (
              <div className="hero-stat live">
                <strong>{live.length}</strong>
                <span>live now</span>
              </div>
            )}
            <div className="hero-stat">
              <strong>{data?.matches?.length ?? '—'}</strong>
              <span>matches</span>
            </div>
          </div>
        </div>

        <div className="wc-hero-bar">
          <span className="wc-source-note">
            🟢 Live scores from ESPN · 💸 Exact payouts pulled from Stake when you open a match
          </span>
          <button
            type="button"
            className={`refresh-btn ${refreshing ? 'is-busy' : ''}`}
            onClick={() => load(matchday, true)}
            disabled={refreshing}
          >
            <span className="refresh-icon" aria-hidden>↻</span>
            {refreshing ? 'Refreshing…' : 'Refresh now'}
          </button>
        </div>

        <p className="budget-banner">
          You have <strong>{formatINR(perMatchBudget)} per game</strong> ·{' '}
          <Link to="/app/settings">change budget</Link>
        </p>

        <div className="md-tabs" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.id === null ? 'today' : String(t.id)}
              className={matchday === t.id ? 'md-tab active' : 'md-tab'}
              onClick={() => setMatchday(t.id)}
              role="tab"
              aria-selected={matchday === t.id}
            >
              {t.label}
              {t.sub && <span className="md-tab-sub">{t.sub}</span>}
            </button>
          ))}
        </div>
      </header>

      {error && (
        <div className="error-banner fade-up" role="alert">
          <span className="error-icon" aria-hidden>⚠️</span>
          <div>
            <strong>Couldn't load matches.</strong>
            <p>{error}</p>
          </div>
          <button className="btn-retry" onClick={() => load(matchday, true)}>Try again</button>
        </div>
      )}

      {loading ? (
        <section className="section">
          <div className="section-head"><h2>Loading matches</h2></div>
          <div className="matches-list">
            <MatchSkeleton />
            <MatchSkeleton />
            <MatchSkeleton />
          </div>
        </section>
      ) : (
        <>
          {live.length > 0 && (
            <section className="section">
              <div className="section-head">
                <h2><span className="live-dot" /> Live now</h2>
                <span className="section-count">{live.length}</span>
              </div>
              <div className="matches-list stagger">
                {live.map((m) => (
                  <MatchCard key={m.fixture_id} m={m} expanded={expanded} onToggle={toggle} variant="live" />
                ))}
              </div>
            </section>
          )}

          <section className="section">
            <div className="section-head">
              <h2>
                {matchday === 0 ? 'All matches' : matchday ? `Matchday ${matchday}` : `Matchday ${data?.active_matchday || ''} — today`}
              </h2>
              {upcoming.length > 0 && (
                <span className="section-count">{upcoming.length} upcoming</span>
              )}
            </div>
            {upcoming.length > 0 ? (
              <div className="matches-list stagger">
                {upcoming.map((m) => (
                  <MatchCard key={m.fixture_id} m={m} expanded={expanded} onToggle={toggle} variant="upcoming" />
                ))}
              </div>
            ) : (
              !data?.matches?.length && (
                <div className="empty-state">
                  <span className="empty-icon" aria-hidden>🗓️</span>
                  <h3>No matches here yet</h3>
                  <p>Try another matchday tab, or refresh to pull the latest fixtures.</p>
                </div>
              )
            )}
          </section>

          {completed.length > 0 && (
            <section className="section finished-section">
              <button className="finished-toggle" onClick={() => setShowFinished((v) => !v)}>
                <span><span className="ft-pill sm">FT</span> Finished games <span className="section-count inline">{completed.length}</span></span>
                <span className={`chevron ${showFinished ? 'up' : ''}`} aria-hidden>⌄</span>
              </button>
              {showFinished && (
                <div className="matches-list stagger" style={{ marginTop: 'var(--sp-4)' }}>
                  {completed.map((m) => (
                    <MatchCard key={m.fixture_id} m={m} expanded={expanded} onToggle={toggle} variant="completed" />
                  ))}
                </div>
              )}
            </section>
          )}
        </>
      )}

      <footer className="wc-footer">
        18+ only · This is analytical software, not financial advice. Bet only money you can afford to lose.
        If it stops being fun, stop.
      </footer>
    </div>
  )
}
