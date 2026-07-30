import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  fetchEvents, fetchAnalysis, fetchWorldCup, fetchErrorMessage,
  refreshStakeOverlay,
} from '../api'
import { useBankroll, formatINR } from '../context/BankrollContext'
import VerdictBadge from '../components/VerdictBadge'
import MatchSlipPanel from '../components/MatchSlipPanel'
import TeamLogo from '../components/TeamLogo'
import {
  SPORT_GROUPS, groupForSportKey, leagueMeta,
  fetchSportKey, filterRowsForLeague, emptyBoardMessage, matchScoreParts,
} from '../data/sportBoard'
import './pages.css'

const WC_KEY = 'soccer_fifa_world_cup'
const PAGE = 12
const TOP_PICK_SCAN = 4

function fmtKickoff(iso) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString(undefined, {
      weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function pct(x) {
  if (x == null) return '-'
  const n = Number(x)
  if (n <= 1) return `${Math.round(n * 100)}%`
  return `${Math.round(n)}%`
}

function fmtOdds(n) {
  if (n == null || !Number(n)) return null
  return Number(n).toFixed(2)
}

function rowVerdict(m) {
  if (m?._wc) {
    const slip = m.bet_slip
    if (slip?.verdict === 'SKIP_MATCH' || slip?.recommended_strategy === 'skip') return 'SKIP_MATCH'
    if (slip?.verdict) return slip.verdict
    return m.verdict?.verdict
  }
  return m?.verdict?.verdict
}

function OddsBtn({ label, value, stake }) {
  const v = fmtOdds(value)
  return (
    <button type="button" className={`odds-btn ${v ? '' : 'is-empty'} ${stake ? 'is-stake' : ''}`.trim()} tabIndex={-1}>
      <span className="odds-btn-label">{label}{stake ? ' · S' : ''}</span>
      <span className="odds-btn-price">{v || '-'}</span>
    </button>
  )
}

function hotScore(ev) {
  // Prefer popular upcoming (books/handle) over "next kickoff".
  let s = 0
  if (ev.status === 'live') s += 1400
  if (ev.status === 'upcoming') s += 300
  const handle = Number(ev.handle_usd || ev.extra?.handle_usd || 0)
  if (handle > 0) s += Math.min(400, Math.log10(handle + 10) * 80)
  const bettors = Number(ev.bettors || ev.extra?.bettors || 0)
  if (bettors > 0) s += Math.min(250, Math.log10(bettors + 10) * 55)
  const books = Number(ev.books || ev.bookmakers?.length || 0)
  if (books > 0) s += Math.min(120, books * 18)
  if (ev.odds?.home || ev.odds?.away) s += 80
  if (ev.odds_source === 'stake' || ev.source === 'stake') s += 110
  if (ev.kickoff) {
    const mins = (new Date(ev.kickoff) - Date.now()) / 60000
    if (mins >= -15 && mins < 36 * 60) s += 55
    else if (mins >= 0 && mins < 72 * 60) s += 25
  }
  return s
}

export default function MatchesPage() {
  const { perMatchBudget, targetCashout, bettorStyle } = useBankroll()
  const [params, setParams] = useSearchParams()
  const initialKey = params.get('sport') || localStorage.getItem('active_sport') || 'soccer_epl'
  const initialGroup = groupForSportKey(initialKey)

  const [sportGroup, setSportGroup] = useState(initialGroup.id)
  const [sport, setSport] = useState(
    initialKey === 'soccer_all' ? 'soccer_other' : initialKey,
  )
  const [rows, setRows] = useState([])
  const [meta, setMeta] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [visible, setVisible] = useState(PAGE)
  const [expanded, setExpanded] = useState(null)
  const [analysis, setAnalysis] = useState(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [topPicks, setTopPicks] = useState([])
  const [picksLoading, setPicksLoading] = useState(false)
  const [stakeMsg, setStakeMsg] = useState(null)
  const [stakeBusy, setStakeBusy] = useState(false)

  const group = SPORT_GROUPS.find((g) => g.id === sportGroup) || SPORT_GROUPS[0]
  const leagues = group.leagues
  const apiSport = fetchSportKey(sport)

  useEffect(() => {
    localStorage.setItem('active_sport', sport)
    const next = new URLSearchParams(params)
    if (next.get('sport') !== sport) {
      next.set('sport', sport)
      setParams(next, { replace: true })
    }
    setLoading(true)
    setErr(null)
    setExpanded(null)
    setAnalysis(null)
    setTopPicks([])
    setVisible(PAGE)

    if (apiSport === WC_KEY) {
      fetchWorldCup({
        matchday: 0,
        budgetPerMatchInr: perMatchBudget,
        targetCashoutInr: targetCashout,
        includeCompleted: true,
      })
        .then((r) => {
          const matches = (r.matches || []).map((m) => ({
            id: m.fixture_id || m.id,
            home_team: m.home_team,
            away_team: m.away_team,
            league: m.stage_label || (m.group ? `Group ${m.group}` : 'World Cup'),
            kickoff: m.kickoff,
            status: m.status,
            score: m.score,
            home_score: m.home_score,
            away_score: m.away_score,
            home_logo: m.home_logo,
            away_logo: m.away_logo,
            odds: {
              home: m.home_odds || m.odds?.home,
              draw: m.draw_odds || m.odds?.draw,
              away: m.away_odds || m.odds?.away,
            },
            odds_source: m.odds_source || m.source,
            source: m.odds_source || 'worldcup',
            _wc: true,
            ...m,
          }))
          setRows(matches)
          setMeta({
            sport_name: 'World Cup',
            source: r.source || 'espn',
            live: true,
            message: `${matches.length} fixtures`,
          })
          setLoading(false)
        })
        .catch((e) => {
          setErr(fetchErrorMessage(e, 'Could not load World Cup'))
          setLoading(false)
        })
      return
    }

    fetchEvents(apiSport)
      .then((r) => {
        const filtered = filterRowsForLeague(r.events || [], sport)
        setRows(filtered)
        setMeta({
          ...r,
          sport_name: leagueMeta(sport).name,
          message: sport === 'soccer_other'
            ? `${filtered.length} fixtures outside the top leagues`
            : r.message,
        })
        setLoading(false)
      })
      .catch((e) => {
        setErr(fetchErrorMessage(e, 'Could not load fixtures'))
        setLoading(false)
      })
  }, [sport, apiSport, perMatchBudget, targetCashout, reloadKey])

  const ordered = useMemo(() => {
    const live = rows.filter((r) => r.status === 'live')
    const upcoming = rows.filter((r) => r.status !== 'live' && r.status !== 'completed')
    const done = rows.filter((r) => r.status === 'completed')
    return [...live, ...upcoming, ...done]
  }, [rows])

  const featured = useMemo(() => {
    return [...ordered]
      .filter((r) => r.status === 'live' || r.status === 'upcoming')
      .sort((a, b) => hotScore(b) - hotScore(a))
      .slice(0, 5)
  }, [ordered])

  const shown = ordered.slice(0, visible)
  const hasMore = visible < ordered.length

  useEffect(() => {
    if (loading || apiSport === WC_KEY) {
      if (apiSport === WC_KEY && !loading) {
        const picks = ordered
          .filter((m) => m.status === 'live' || m.status === 'upcoming')
          .slice(0, TOP_PICK_SCAN)
          .flatMap((m) => {
            const legs = (m.bet_slip?.strategies?.min_loss?.[0]?.legs
              || m.unified_picks
              || m.top_bets
              || []).slice(0, 2)
            return legs.map((b) => ({
              match: `${m.home_team} vs ${m.away_team}`,
              eventId: m.id,
              label: b.label || b.selection || b.market,
              win: b.true_probability ?? b.our_probability ?? b.win_probability,
              odds: b.decimal_odds || b.odds || b.best_odds,
              stake: b.stake_inr || b.stake_recommendation?.recommended_stake,
              _wc: true,
              raw: m,
            }))
          })
          .slice(0, 8)
        setTopPicks(picks)
      }
      return
    }
    const targets = ordered
      .filter((r) => r.status === 'live' || r.status === 'upcoming')
      .slice(0, TOP_PICK_SCAN)
    if (!targets.length) {
      setTopPicks([])
      return
    }
    let cancelled = false
    setPicksLoading(true)
    Promise.allSettled(
      targets.map((ev) => fetchAnalysis({
        sport: apiSport,
        eventId: ev.id,
        bankroll: perMatchBudget,
        targetCashoutInr: targetCashout,
      }).then((r) => ({ ev, a: r.matches?.[0] }))),
    ).then((results) => {
      if (cancelled) return
      const picks = []
      for (const res of results) {
        if (res.status !== 'fulfilled' || !res.value?.a) continue
        const { ev, a } = res.value
        for (const b of (a.suggested_bets || []).slice(0, 2)) {
          picks.push({
            match: `${ev.home_team} vs ${ev.away_team}`,
            eventId: ev.id,
            label: b.label || b.selection,
            win: b.true_probability ?? b.our_probability,
            odds: b.decimal_odds || b.odds,
            stake: b.stake_recommendation?.recommended_stake,
            raw: a,
          })
        }
      }
      setTopPicks(picks.slice(0, 8))
      setPicksLoading(false)
    })
    return () => { cancelled = true }
  }, [loading, ordered, apiSport, perMatchBudget, targetCashout, bettorStyle])

  const openMatch = (ev) => {
    if (expanded === ev.id) {
      setExpanded(null)
      return
    }
    setExpanded(ev.id)
    if (ev._wc) {
      setAnalysis(ev)
      setAnalyzing(false)
      return
    }
    setAnalyzing(true)
    setAnalysis(null)
    fetchAnalysis({
      sport: apiSport,
      eventId: ev.id,
      bankroll: perMatchBudget,
      targetCashoutInr: targetCashout,
    })
      .then((r) => {
        setAnalysis(r.matches?.[0] || null)
        setAnalyzing(false)
      })
      .catch((e) => {
        setErr(fetchErrorMessage(e, 'Analysis failed'))
        setAnalyzing(false)
      })
  }

  const selectGroup = (id) => {
    const g = SPORT_GROUPS.find((x) => x.id === id)
    if (!g) return
    setSportGroup(id)
    setSport(g.leagues[0].key)
  }

  const connectStake = async () => {
    setStakeBusy(true)
    setStakeMsg(null)
    try {
      try {
        window.open('https://stake.com/', '_blank', 'noopener,noreferrer')
      } catch { /* popup blocked */ }
      const r = await refreshStakeOverlay()
      setStakeMsg(
        r?.message
        || (r?.skipped
          ? `Using ${r?.fixtures ?? 0} cached Stake prices. Use Admin → Request laptop odds sync for fresh lines.`
          : 'Stake cache refreshed. Refresh the board for prices.')
      )
      setReloadKey((k) => k + 1)
    } catch (e) {
      setStakeMsg(fetchErrorMessage(e, 'Stake refresh failed'))
    } finally {
      setStakeBusy(false)
    }
  }

  const slipOpen = expanded && analysis

  return (
    <div className="dash">
      <div className="dash-main">
        <header className="board-top">
          <div>
            <h1>Matches</h1>
            <p className="muted">Live and upcoming boards</p>
          </div>
          <button type="button" className="btn-secondary" onClick={() => setReloadKey((k) => k + 1)} disabled={loading}>
            Refresh
          </button>
        </header>

        <section className="featured-rail" aria-label="Featured matches">
          <div className="section-label">Featured</div>
          {loading && <p className="muted">Loading fixtures…</p>}
          {!loading && !featured.length && (
            <p className="muted">{emptyBoardMessage(rows, leagueMeta(sport).name) || 'No live or upcoming fixtures on this board.'}</p>
          )}
          <div className="featured-track">
            {featured.map((ev) => (
              <button
                key={`hot-${ev.id}`}
                type="button"
                className={`featured-card ${ev.status === 'live' ? 'is-live' : ''}`}
                onClick={() => openMatch(ev)}
              >
                {ev.status === 'live' ? <span className="live-tag">LIVE</span> : <span className="ft-tag">UP</span>}
                <div className="featured-teams">
                  <TeamLogo name={ev.home_team} src={ev.home_logo} size={22} />
                  <span>{ev.home_team}</span>
                </div>
                <div className="featured-teams">
                  <TeamLogo name={ev.away_team} src={ev.away_logo} size={22} />
                  <span>{ev.away_team}</span>
                </div>
                <small>{fmtKickoff(ev.kickoff) || ev.league}</small>
              </button>
            ))}
          </div>
        </section>

        <nav className="sport-tabs" aria-label="Sports">
          {SPORT_GROUPS.map((g) => (
            <button
              key={g.id}
              type="button"
              className={`sport-tab ${sportGroup === g.id ? 'active' : ''}`}
              onClick={() => selectGroup(g.id)}
            >
              {g.name}
            </button>
          ))}
        </nav>

        <nav className="league-tabs" aria-label="Leagues">
          {leagues.map((lg) => (
            <button
              key={lg.key}
              type="button"
              className={`league-tab ${sport === lg.key ? 'active' : ''} ${lg.top === false ? 'is-other' : ''}`}
              onClick={() => setSport(lg.key)}
            >
              {lg.logo ? (
                <img src={lg.logo} alt="" className="league-tab-logo" loading="lazy" />
              ) : null}
              <span>{lg.name}</span>
            </button>
          ))}
        </nav>

        <section className="top-picks-block">
          <div className="section-label">Top recommended</div>
          {picksLoading && <p className="muted">Scanning open fixtures…</p>}
          {!picksLoading && !topPicks.length && (
            <p className="muted">No clear edges on the scanned matches. Open a fixture or change your style.</p>
          )}
          <div className="top-picks-list">
            {topPicks.map((p, i) => (
              <button
                key={`${p.eventId}-${i}`}
                type="button"
                className="top-pick-row"
                onClick={() => {
                  const ev = rows.find((r) => r.id === p.eventId) || p.raw
                  if (ev) openMatch(ev)
                }}
              >
                <div>
                  <strong>{p.label}</strong>
                  <div className="muted">{p.match}</div>
                </div>
                <div className="top-pick-meta">
                  <span>{pct(p.win)}</span>
                  <span className="green">{fmtOdds(p.odds) || '-'}</span>
                  <span>{p.stake ? formatINR(p.stake) : '-'}</span>
                </div>
              </button>
            ))}
          </div>
        </section>

        {meta && (
          <div className="board-meta">
            <span>{leagueMeta(sport).name}</span>
            <span className="dot-sep" />
            <span>{meta.source}</span>
            <span className="dot-sep" />
            <span>{ordered.length} matches</span>
            {meta.message && (
              <>
                <span className="dot-sep" />
                <span>{meta.message}</span>
              </>
            )}
          </div>
        )}

        {err && <p className="muted" role="alert">{err}</p>}

        <div className="fixture-table">
          {shown.map((ev) => {
            const open = expanded === ev.id
            const a = open ? analysis : null
            const v = open && a ? rowVerdict(a) : (ev._wc ? rowVerdict(ev) : null)
            const parts = matchScoreParts(ev)
            const odds = ev.odds || {}
            const fromStake = (ev.odds_source || ev.source || '').includes('stake')

            return (
              <article key={ev.id} className={`fixture-row ${open ? 'is-open' : ''} ${ev.status === 'live' ? 'is-live' : ''}`}>
                <button type="button" className="fixture-main" onClick={() => openMatch(ev)}>
                  <div className="fixture-time">
                    {ev.status === 'live' ? <span className="live-tag">LIVE</span> : null}
                    {ev.status === 'completed' ? <span className="ft-tag">FT</span> : null}
                    <span className="fixture-kick">
                      {ev.status === 'live' && ev.status_detail
                        ? ev.status_detail
                        : (fmtKickoff(ev.kickoff) || 'TBD')}
                    </span>
                    {ev.league && <span className="fixture-comp">{ev.league}</span>}
                  </div>
                  <div className="fixture-teams">
                    <div className="fixture-side">
                      <TeamLogo name={ev.home_team} src={ev.home_logo} size={28} sport={sportGroup} />
                      <span className="fixture-name">{ev.home_team}</span>
                      {parts && <span className="fixture-score">{parts.home}</span>}
                    </div>
                    <div className="fixture-side">
                      <TeamLogo name={ev.away_team} src={ev.away_logo} size={28} sport={sportGroup} />
                      <span className="fixture-name">{ev.away_team}</span>
                      {parts && <span className="fixture-score">{parts.away}</span>}
                    </div>
                  </div>
                  <div className="fixture-odds" onClick={(e) => e.stopPropagation()}>
                    <OddsBtn label="1" value={odds.home} stake={fromStake} />
                    {sportGroup === 'soccer' && <OddsBtn label="X" value={odds.draw} stake={fromStake} />}
                    <OddsBtn label="2" value={odds.away} stake={fromStake} />
                  </div>
                  {v && <VerdictBadge verdict={v} />}
                </button>

                {open && (
                  <div className="fixture-detail">
                    {analyzing && <p className="muted">Running analysis…</p>}
                    {!analyzing && a?._wc && (
                      <MatchSlipPanel
                        slip={a.bet_slip}
                        home={a.home_team}
                        away={a.away_team}
                        fanPrediction={a.fan_prediction}
                        status={a.status}
                        score={a.score}
                      />
                    )}
                    {!analyzing && a && !a._wc && (
                      <>
                        {a.verdict?.headline && <p className="panel-desc">{a.verdict.headline}</p>}
                        {a.verdict?.reasoning && <p className="muted">{a.verdict.reasoning}</p>}
                        <h3 className="panel-subtitle">Picks</h3>
                        {(a.suggested_bets || []).length === 0 ? (
                          <p className="muted">No picks clear your thresholds. Skip.</p>
                        ) : (
                          <table className="data-table">
                            <thead>
                              <tr>
                                <th>Pick</th>
                                <th>Win%</th>
                                <th>Odds</th>
                                <th>Stake</th>
                              </tr>
                            </thead>
                            <tbody>
                              {(a.suggested_bets || []).map((b, i) => (
                                <tr key={i}>
                                  <td>
                                    <strong>{b.label || b.selection}</strong>
                                    {b.explanation && <div className="muted" style={{ marginTop: 4 }}>{b.explanation}</div>}
                                  </td>
                                  <td>{pct(b.true_probability ?? b.our_probability)}</td>
                                  <td>{Number(b.decimal_odds || b.odds || 0).toFixed(2)}</td>
                                  <td>
                                    {b.stake_recommendation
                                      ? formatINR(b.stake_recommendation.recommended_stake)
                                      : '-'}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </>
                    )}
                  </div>
                )}
              </article>
            )
          })}
        </div>

        {hasMore && (
          <button type="button" className="btn-secondary load-more" onClick={() => setVisible((v) => v + PAGE)}>
            Load more ({ordered.length - visible} left)
          </button>
        )}
      </div>

      <aside className="dash-rail">
        <div className="rail-card">
          <small className="section-label">Stake odds</small>
          <p className="muted rail-hint">
            Board shows ESPN prices by default. Connect Stake to overlay placeable 1X2 where matched.
          </p>
          <button type="button" className="btn-secondary" onClick={connectStake} disabled={stakeBusy}>
            {stakeBusy ? 'Connecting…' : 'Connect Stake'}
          </button>
          {stakeMsg && <p className="muted rail-hint">{stakeMsg}</p>}
        </div>

        <div className="rail-card rail-slip">
          <small className="section-label">Slip</small>
          {!slipOpen && <p className="muted rail-hint">Open a match to park picks here.</p>}
          {slipOpen && analyzing && <p className="muted">Loading…</p>}
          {slipOpen && !analyzing && analysis?._wc && (
            <MatchSlipPanel
              slip={analysis.bet_slip}
              home={analysis.home_team}
              away={analysis.away_team}
              fanPrediction={analysis.fan_prediction}
              status={analysis.status}
              score={analysis.score}
            />
          )}
          {slipOpen && !analyzing && analysis && !analysis._wc && (
            <ul className="rail-pick-list">
              {(analysis.suggested_bets || []).length === 0 && (
                <li className="muted">Skip this match.</li>
              )}
              {(analysis.suggested_bets || []).map((b, i) => (
                <li key={i}>
                  <strong>{b.label || b.selection}</strong>
                  <span>{pct(b.true_probability ?? b.our_probability)} @ {Number(b.decimal_odds || b.odds || 0).toFixed(2)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </aside>
    </div>
  )
}
