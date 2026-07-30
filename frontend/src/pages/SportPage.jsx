import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  fetchEvents, fetchAnalysis, fetchWorldCup, fetchErrorMessage, fetchMarketTop, peekEventsCache, peekMarketTop,
} from '../api'
import { useBankroll, formatINR } from '../context/BankrollContext'
import MatchSlipPanel from '../components/MatchSlipPanel'
import BoardBuffer from '../components/BoardBuffer'
import { useEntryReady } from '../components/EntryScreen'
import TeamLogo from '../components/TeamLogo'
import VerdictBadge from '../components/VerdictBadge'
import {
  FeaturedCard, LeagueBanner, OddsBtn, LoadMore, pickFeatured,
  fmtKickoff, pct, marketPicksFromRows,
} from '../components/BoardBits'
import TopBetTicket from '../components/TopBetTicket'
import {
  SPORT_GROUPS, fetchSportKey, filterRowsForLeague, boardForBetting,
  emptyBoardMessage, matchScoreParts, leagueTabForEvent,
} from '../data/sportBoard'
import { legFromBet } from '../lib/slipRules'
import './pages.css'

const WC_KEY = 'soccer_fifa_world_cup'
const PAGE = 20
const TOP_PICK_SCAN = 3
const MAX_SUGGESTED = 3

function MatchStatsStrip({ home, away, stats, probs }) {
  if (!stats?.home && !stats?.away && !probs) return null
  const h = stats?.home || {}
  const a = stats?.away || {}
  const cells = [
    probs?.home != null && { label: 'Win%', home: pct(probs.home), away: pct(probs.away) },
    (h.form || a.form) && { label: 'Form', home: h.form || 'n/a', away: a.form || 'n/a' },
    (h.xg != null || a.xg != null) && { label: 'xG', home: h.xg ?? 'n/a', away: a.xg ?? 'n/a' },
    (h.xga != null || a.xga != null) && { label: 'xGA', home: h.xga ?? 'n/a', away: a.xga ?? 'n/a' },
    (h.goals_for != null || a.goals_for != null) && {
      label: 'GF/GA',
      home: `${h.goals_for ?? 'n/a'} / ${h.goals_against ?? 'n/a'}`,
      away: `${a.goals_for ?? 'n/a'} / ${a.goals_against ?? 'n/a'}`,
    },
  ].filter(Boolean)
  if (!cells.length) return null
  return (
    <div className="match-stats-strip">
      <div className="match-stats-head">
        <span>{home}</span>
        <span className="muted">Stats</span>
        <span>{away}</span>
      </div>
      {cells.map((c) => (
        <div key={c.label} className="match-stats-row">
          <strong>{c.home}</strong>
          <span className="muted">{c.label}</span>
          <strong>{c.away}</strong>
        </div>
      ))}
    </div>
  )
}

function probsFromAnalysis(a) {
  const list = a?.probabilities || []
  const home = list.find((p) => p.selection === 'home' || /home|1$/i.test(p.label || ''))
  const away = list.find((p) => p.selection === 'away' || /away|2$/i.test(p.label || ''))
  const draw = list.find((p) => p.selection === 'draw' || /draw|x/i.test(p.label || ''))
  if (!home && !away) return null
  return {
    home: home?.probability ?? home?.true_probability,
    draw: draw?.probability ?? draw?.true_probability,
    away: away?.probability ?? away?.true_probability,
  }
}

function pickEdgeLine(b) {
  const model = b.model_pct ?? (b.true_probability != null ? Math.round(Number(b.true_probability) * 100) : null)
  const book = b.book_pct
  const odds = Number(b.decimal_odds || b.odds || 0)
  if (model != null && book != null) return `Model ${model}% · book ~${book}%`
  if (model != null && odds > 1) return `Model ${model}% · @ ${odds.toFixed(2)}`
  return null
}

function AnalysisBrief({ a, analyzing, onAdd, onPark, ev }) {
  if (analyzing && !a?.verdict) {
    return <p className="muted">Running model…</p>
  }
  if (!a) return null
  const picks = (a.suggested_bets || []).slice(0, MAX_SUGGESTED)
  const v = a.verdict || {}
  const probs = probsFromAnalysis(a)
  return (
    <div className="analysis-brief">
      <div className="analysis-brief-head">
        <div>
          {v.headline ? <strong>{v.headline.replace(/^(BET|CAUTION|SKIP)\s*[-\u2013\u2014]\s*/i, '')}</strong> : null}
          {a.style_note ? <p className="muted">{a.style_note}</p> : null}
        </div>
        {v.verdict ? <VerdictBadge verdict={v.verdict} /> : null}
      </div>
      {probs && (
        <div className="analysis-edge" aria-label="Model win probabilities">
          <span>Win% <em>{pct(probs.home)}</em></span>
          {probs.draw != null && <span>Draw <em>{pct(probs.draw)}</em></span>}
          <span>Away <em>{pct(probs.away)}</em></span>
        </div>
      )}
      {(v.reasoning || []).length > 0 && (
        <ul className="reason-list">
          {v.reasoning.slice(0, 3).map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      )}
      <div className="picks-head">
        <h3 className="panel-subtitle">Recommended</h3>
        {picks.length > 1 && onPark && (
          <button type="button" className="btn-secondary tight" onClick={() => onPark(ev, a)}>
            Add as SGM
          </button>
        )}
      </div>
      {picks.length === 0 ? (
        <div className="analysis-brief-empty">
          <p className="muted">Model picks pending — use 1 / X / 2 above to add a result, or wait for Recs below.</p>
          {ev?.odds?.home && (
            <div className="analysis-quick-add">
              <button type="button" className="btn-secondary tight" onClick={() => onAdd(ev, {
                selection: 'home', label: `${ev.home_team} to win`, decimal_odds: ev.odds.home,
                market: 'match_winner', market_name: 'Match Result',
              })}>
                Add {ev.home_team} @ {Number(ev.odds.home).toFixed(2)}
              </button>
              {ev.odds.draw != null && (
                <button type="button" className="btn-secondary tight" onClick={() => onAdd(ev, {
                  selection: 'draw', label: 'Draw', decimal_odds: ev.odds.draw,
                  market: 'match_winner', market_name: 'Match Result',
                })}>
                  Add Draw @ {Number(ev.odds.draw).toFixed(2)}
                </button>
              )}
              {ev.odds.away && (
                <button type="button" className="btn-secondary tight" onClick={() => onAdd(ev, {
                  selection: 'away', label: `${ev.away_team} to win`, decimal_odds: ev.odds.away,
                  market: 'match_winner', market_name: 'Match Result',
                })}>
                  Add {ev.away_team} @ {Number(ev.odds.away).toFixed(2)}
                </button>
              )}
            </div>
          )}
        </div>
      ) : (
        <table className="data-table">
          <thead>
            <tr><th>Market</th><th>Selection</th><th>Odds</th><th>Stake</th><th /></tr>
          </thead>
          <tbody>
            {picks.map((b, i) => {
              const edge = pickEdgeLine(b)
              return (
                <tr key={i}>
                  <td className="muted">{b.market_name || 'Match Result'}</td>
                  <td>
                    <strong>{b.label || b.selection}</strong>
                    {b.is_lean ? <span className="muted"> · lean</span> : null}
                    {edge ? <span className="pick-edge">{edge}</span> : null}
                  </td>
                  <td>{Number(b.decimal_odds || b.odds || 0).toFixed(2)}</td>
                  <td>{b.stake_recommendation ? formatINR(b.stake_recommendation.recommended_stake) : '-'}</td>
                  <td>
                    <button type="button" className="btn-secondary tight" onClick={() => onAdd(ev, b)}>
                      Add
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}

function rowVerdict(m) {
  if (!m) return null
  if (m?._wc) {
    const slip = m.bet_slip
    const hasPicks = Boolean(
      slip?.curated_picks?.primary?.legs?.length
      || slip?.easy_money?.length
      || slip?.recommended_singles?.length
      || slip?.unified_picks?.length
      || (slip?.strategies && Object.values(slip.strategies).some((v) => (Array.isArray(v) ? v : [v]).some((p) => p?.legs?.length)))
    )
    if (slip?.verdict === 'BET') return 'BET'
    if (slip?.verdict === 'SKIP_MATCH' || slip?.recommended_strategy === 'skip') {
      return hasPicks ? 'CAUTION' : 'SKIP'
    }
    if (slip?.skip_recommended && hasPicks) return 'CAUTION'
    if (slip?.verdict) return slip.verdict
    return m.verdict?.verdict
  }
  const v = m?.verdict?.verdict || m?.verdict
  const raw = typeof v === 'string' ? v : (v?.value || null)
  if (raw === 'SKIP' || raw === 'skip') return 'SKIP'
  return raw
}

export default function SportPage() {
  const { sportId } = useParams()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const group = SPORT_GROUPS.find((g) => g.id === sportId) || SPORT_GROUPS[0]
  const { perMatchBudget, targetCashout, bettorStyle, addLeg, setSlipOpen } = useBankroll()

  const focusId = params.get('focus')
  const initialLeague = params.get('league') || group.leagues[0].key

  const [sport, setSport] = useState(initialLeague)
  const [rows, setRows] = useState([])
  const [meta, setMeta] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [visible, setVisible] = useState(PAGE)
  const [expanded, setExpanded] = useState(focusId)
  const [analysis, setAnalysis] = useState(null)
  const [analyzing, setAnalyzing] = useState(false)
  const analysisReq = useRef(0)
  const [topPicks, setTopPicks] = useState([])
  const [picksLoading, setPicksLoading] = useState(false)
  useEntryReady(!loading)

  const apiSport = fetchSportKey(sport)
  const activeLeague = group.leagues.find((l) => l.key === sport) || group.leagues[0]

  const applyLeagueRows = (events, leagueKey, source, message) => {
    const filtered = filterRowsForLeague(events || [], leagueKey)
    setRows(filtered)
    setMeta({
      source,
      message: leagueKey === 'soccer_other'
        ? `${filtered.length} fixtures outside the top leagues`
        : (message || `${filtered.length} fixtures`),
    })
  }

  const selectLeague = (key) => {
    if (key === sport) return
    setSport(key)
    setExpanded(null)
    setAnalysis(null)
    setTopPicks([])
    setVisible(PAGE)
    setErr(null)
    // Instant swap from cache so the board doesn't keep showing the previous league
    const fetchKey = fetchSportKey(key)
    const cached = peekEventsCache(fetchKey)
    if (cached?.events) {
      applyLeagueRows(cached.events, key, cached.source, cached.message)
      setLoading(false)
    } else {
      setRows([])
      setLoading(true)
    }
  }

  useEffect(() => {
    // Switching sport category - honor ?league= when valid, else first tab
    const fromUrl = params.get('league')
    const next = (fromUrl && group.leagues.some((l) => l.key === fromUrl))
      ? fromUrl
      : group.leagues[0].key
    setSport(next)
    setVisible(PAGE)
    // Keep focus expand when deep-linking into this sport
    if (!params.get('focus')) {
      setExpanded(null)
      setAnalysis(null)
    }
    const fetchKey = fetchSportKey(next)
    const cached = peekEventsCache(fetchKey)
    if (cached?.events) {
      applyLeagueRows(cached.events, next, cached.source, cached.message)
      setLoading(false)
    } else {
      setRows([])
      setLoading(true)
    }
  }, [group.id])

  useEffect(() => {
    const next = new URLSearchParams(params)
    if (next.get('league') !== sport) {
      next.set('league', sport)
      setParams(next, { replace: true })
    }
    setErr(null)

    if (apiSport === WC_KEY) {
      setLoading(true)
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
          setMeta({ source: r.source || 'espn', message: `${matches.length} fixtures` })
          setLoading(false)
        })
        .catch((e) => {
          setErr(fetchErrorMessage(e, 'Could not load World Cup'))
          setLoading(false)
        })
      return undefined
    }

    const cached = peekEventsCache(apiSport)
    if (cached?.events) {
      applyLeagueRows(cached.events, sport, cached.source, cached.message)
      setLoading(false)
    } else {
      setLoading(true)
    }

    let cancelled = false
    const leagueAtStart = sport
    fetchEvents(apiSport)
      .then((r) => {
        if (cancelled) return
        applyLeagueRows(r.events || [], leagueAtStart, r.source, r.message)
        setLoading(false)
      })
      .catch((e) => {
        if (cancelled) return
        if (!peekEventsCache(apiSport)?.events) {
          setErr(fetchErrorMessage(e, 'Could not load fixtures'))
          setLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [sport, apiSport, reloadKey, group.id])

  const liveUpcoming = useMemo(
    () => rows.filter((r) => r.status === 'live' || r.status === 'upcoming'),
    [rows],
  )
  const featured = useMemo(() => pickFeatured(rows, 8), [rows])
  const board = useMemo(
    () => boardForBetting(rows, { minUpcoming: 24, days: 14, sportId: group.id }),
    [rows, group.id],
  )
  const shown = board.slice(0, visible)

  useEffect(() => {
    if (loading) return undefined
    if (apiSport === WC_KEY) {
      const picks = liveUpcoming.slice(0, TOP_PICK_SCAN).flatMap((m) => {
        const legs = (m.bet_slip?.strategies?.min_loss?.[0]?.legs || m.unified_picks || m.top_bets || []).slice(0, 2)
        return legs.map((b) => ({
          event_id: m.id,
          home_team: m.home_team,
          away_team: m.away_team,
          home_logo: m.home_logo,
          away_logo: m.away_logo,
          sport_key: WC_KEY,
          league: m.league || 'World Cup',
          label: b.label || b.selection || b.market,
          selection: b.selection || b.label,
          market: b.market || 'match_winner',
          market_name: b.market_name || 'Match Result',
          decimal_odds: Number(b.decimal_odds || b.odds || b.best_odds),
          status: m.status,
          raw: m,
          ticket_kind: 'single',
        })).filter((p) => p.decimal_odds >= 1.28)
      }).slice(0, 4)
      setTopPicks(picks)
      setPicksLoading(false)
      return undefined
    }
    let cancelled = false
    const warm = peekMarketTop(12)
    if (warm?.bets?.length) {
      const prefix = group.id === 'basketball' ? 'basket' : group.id === 'cricket' ? 'cricket' : 'soccer'
      const sportBets = (warm.bets || []).filter((b) => String(b.sport_key || '').startsWith(prefix))
      setTopPicks(sportBets.length ? sportBets.slice(0, 6) : marketPicksFromRows(liveUpcoming, 4))
      setPicksLoading(false)
    } else {
      setPicksLoading(true)
    }
    const prefix = group.id === 'basketball' ? 'basket' : group.id === 'cricket' ? 'cricket' : 'soccer'
    fetchMarketTop(12)
      .then((r) => {
        if (cancelled) return
        const sportBets = (r.bets || []).filter((b) => String(b.sport_key || '').startsWith(prefix))
        setTopPicks(sportBets.length ? sportBets.slice(0, 6) : marketPicksFromRows(liveUpcoming, 4))
      })
      .catch(() => {
        if (!cancelled) setTopPicks(marketPicksFromRows(liveUpcoming, 4))
      })
      .finally(() => { if (!cancelled) setPicksLoading(false) })
    return () => { cancelled = true }
  }, [loading, liveUpcoming, apiSport, group.id])

  useEffect(() => {
    if (loading || !rows.length) return
    const focusHome = (params.get('home') || '').toLowerCase()
    const focusAway = (params.get('away') || '').toLowerCase()
    if (!focusId && !focusHome) return

    const ev = rows.find((r) => {
      if (focusId && String(r.id) === String(focusId)) return true
      if (focusHome && focusAway) {
        const h = String(r.home_team || '').toLowerCase()
        const a = String(r.away_team || '').toLowerCase()
        return (h.includes(focusHome) || focusHome.includes(h)) && (a.includes(focusAway) || focusAway.includes(a))
      }
      return false
    })
    if (!ev) return
    // Ensure the focused row is in the painted page (not below Load more)
    const boardIdx = board.findIndex((r) => String(r.id) === String(ev.id))
    if (boardIdx >= 0 && boardIdx >= visible) {
      setVisible(boardIdx + 1)
    }
    setExpanded(ev.id)
    // Scroll the focused fixture into view once boards paint
    const scroll = () => {
      document.getElementById(`fixture-${ev.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
    requestAnimationFrame(scroll)
    setTimeout(scroll, 120)
    if (ev._wc) {
      setAnalysis(ev)
      setAnalyzing(false)
      return
    }
    setAnalyzing(true)
    setAnalysis(null)
    const req = ++analysisReq.current
    fetchAnalysis({
      sport: apiSport,
      eventId: ev.id,
      bankroll: perMatchBudget,
      goal: bettorStyle.goal,
      risk: bettorStyle.risk,
      structure: bettorStyle.structure,
      targetCashoutInr: targetCashout,
    })
      .then((r) => {
        if (analysisReq.current !== req) return
        setAnalysis(r.matches?.[0] || null)
        setAnalyzing(false)
      })
      .catch(() => {
        if (analysisReq.current !== req) return
        setAnalyzing(false)
      })
  }, [focusId, loading, rows, board, visible, apiSport, perMatchBudget, targetCashout, bettorStyle, params])

  // If focus points at another league, switch tab so the fixture exists in `rows`
  useEffect(() => {
    const league = params.get('league')
    if (!league || league === sport) return
    if (!group.leagues.some((l) => l.key === league)) return
    setSport(league)
    // Don't reset visible when focusing a deep-linked match
    if (!params.get('focus')) setVisible(PAGE)
  }, [group.id, params, sport])

  const parkAnalysis = (ev, a) => {
    // Explicit add only - opening a match must not dump legs into the slip
    if (!a) return
    const picks = a._wc
      ? (a.bet_slip?.strategies?.min_loss?.[0]?.legs || a.unified_picks || []).slice(0, MAX_SUGGESTED)
      : (a.suggested_bets || []).slice(0, MAX_SUGGESTED)
    for (const b of picks) {
      addPick(ev, b)
    }
  }

  const addPick = (ev, b) => {
    const stake = Number(b.stake_recommendation?.recommended_stake || b.stake_inr || 0) || null
    addLeg({
      id: `${ev.id}-${b.market || 'm'}-${b.selection || b.label}-${b.decimal_odds || b.odds}`,
      eventId: String(ev.id),
      home: ev.home_team,
      away: ev.away_team,
      homeLogo: ev.home_logo,
      awayLogo: ev.away_logo,
      label: b.label || b.selection || 'Pick',
      marketName: b.market_name || 'Match Result',
      market: b.market || b.label || `pick-${b.selection}`,
      selection: b.selection || b.label,
      odds: Number(b.decimal_odds || b.odds || b.best_odds),
      sportKey: ev.sport_key || apiSport,
      league: ev.league,
      stake,
    })
  }

  const parkBoardOdds = (ev, side = null) => {
    const o = ev.odds || {}
    const picks = [
      (!side || side === 'home') && o.home && {
        selection: 'home', label: `${ev.home_team} to win`, odds: o.home, market: 'match_winner', market_name: 'Match Result',
      },
      (!side || side === 'draw') && o.draw && {
        selection: 'draw', label: 'Draw', odds: o.draw, market: 'match_winner', market_name: 'Match Result',
      },
      (!side || side === 'away') && o.away && {
        selection: 'away', label: `${ev.away_team} to win`, odds: o.away, market: 'match_winner', market_name: 'Match Result',
      },
    ].filter(Boolean)
    // Opening a match shouldn't dump all three sides - only park when a side is chosen
    if (!side) return
    for (const p of picks) {
      addLeg(legFromBet({
        event_id: ev.id,
        home_team: ev.home_team,
        away_team: ev.away_team,
        home_logo: ev.home_logo,
        away_logo: ev.away_logo,
        sport_key: ev.sport_key,
        league: ev.league,
        label: p.label,
        selection: p.selection,
        market: p.market,
        market_name: p.market_name,
        decimal_odds: p.odds,
      }))
    }
  }

  const addFeaturedOdds = (ev, side) => {
    const o = ev.odds || {}
    const price = o[side]
    if (!price) return
    const label = side === 'home' ? `${ev.home_team} to win`
      : side === 'away' ? `${ev.away_team} to win` : 'Draw'
    const ok = addLeg(legFromBet({
      event_id: ev.id,
      home_team: ev.home_team,
      away_team: ev.away_team,
      home_logo: ev.home_logo,
      away_logo: ev.away_logo,
      sport_key: ev.sport_key,
      league: ev.league,
      market: 'match_winner',
      market_name: 'Match Result',
      selection: side,
      label,
      decimal_odds: price,
    }, null))
    if (ok) setSlipOpen?.(true)
  }

  const openMatch = (ev) => {
    // Top bet / featured → deep-link so league + focus survive remounts
    const eid = String(ev.event_id || ev.id || '')
    if (eid && !rows.some((r) => String(r.id) === eid)) {
      const q = new URLSearchParams({ focus: eid })
      const league = leagueTabForEvent(ev) || ev.league_key || ev.sport_key
      if (league) q.set('league', String(league))
      if (ev.home_team) q.set('home', String(ev.home_team))
      if (ev.away_team) q.set('away', String(ev.away_team))
      navigate(`/app/sport/${group.id}?${q}`)
      return
    }
    const id = ev.event_id || ev.id
    const row = rows.find((r) => String(r.id) === String(id)) || ev
    if (expanded === row.id) {
      setExpanded(null)
      return
    }
    setExpanded(row.id)
    // Always bring the row into view when opening from top matches
    const boardIdx = board.findIndex((r) => String(r.id) === String(row.id))
    if (boardIdx >= 0 && boardIdx >= visible) setVisible(boardIdx + 1)
    const scroll = () => {
      document.getElementById(`fixture-${row.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
    requestAnimationFrame(scroll)
    setTimeout(scroll, 160)
    if (row._wc) {
      setAnalysis(row)
      setAnalyzing(false)
      return
    }
    setAnalyzing(true)
    setAnalysis(group.id === 'soccer' ? {
      home_team: row.home_team,
      away_team: row.away_team,
      status: row.status,
      web_consensus: null,
    } : null)
    const req = ++analysisReq.current
    fetchAnalysis({
      sport: apiSport,
      eventId: row.id,
      bankroll: perMatchBudget,
      goal: bettorStyle.goal,
      risk: bettorStyle.risk,
      structure: bettorStyle.structure,
      targetCashoutInr: targetCashout,
    })
      .then((r) => {
        if (analysisReq.current !== req) return
        setAnalysis(r.matches?.[0] || null)
        setAnalyzing(false)
      })
      .catch((e) => {
        if (analysisReq.current !== req) return
        if (group.id !== 'soccer') setErr(fetchErrorMessage(e, 'Analysis failed'))
        setAnalyzing(false)
      })
  }

  return (
    <div className="home-board">
      <header className="board-top">
        <div>
          <p className="crumb">
            <Link to="/app">Home</Link>
            <span> / </span>
            <span>{group.name}</span>
          </p>
          <h1>{group.name}</h1>
          <p className="muted">
            {loading
              ? 'Loading…'
              : `${board.length} live / upcoming · ${activeLeague?.name || ''}`}
          </p>
        </div>
        <div className="board-top-actions">
          <button type="button" className="btn-secondary" onClick={() => navigate('/app')}>All sports</button>
          <button type="button" className="btn-secondary" onClick={() => setReloadKey((k) => k + 1)} disabled={loading}>
            Refresh
          </button>
        </div>
      </header>

      <section className="featured-rail">
        <div className="section-label">Top matches</div>
        {loading && !featured.length && <BoardBuffer rows={4} label="Loading fixtures…" />}
        {!loading && !featured.length && (
          <p className="muted">{emptyBoardMessage(rows, activeLeague?.name) || 'No live or upcoming fixtures in this league.'}</p>
        )}
        {!!featured.length && (
          <div className="featured-track featured-track--four">
            {featured.slice(0, 4).map((ev) => (
              <FeaturedCard
                key={ev.id}
                ev={ev}
                onOpen={openMatch}
                onAddOdds={addFeaturedOdds}
                showDraw={group.id === 'soccer'}
                sport={group.id}
              />
            ))}
          </div>
        )}
      </section>

      <section>
        <div className="section-label">Leagues · {activeLeague?.name}</div>
        <div className="league-banner-row">
          {group.leagues.map((lg) => (
            <LeagueBanner
              key={lg.key}
              league={lg}
              active={sport === lg.key}
              onClick={() => selectLeague(lg.key)}
            />
          ))}
        </div>
      </section>

      <section className="top-picks-block">
        <div className="section-label">Top bets</div>
        <p className="section-sub">Popular singles and combos. Amount optional.</p>
        {picksLoading && !topPicks.length && <BoardBuffer rows={3} label="Loading market…" />}
        {!picksLoading && !topPicks.length && (
          <p className="muted">No priced favorites on this board yet.</p>
        )}
        <div className="bet-ticket-list">
          {topPicks.map((p, i) => (
            <TopBetTicket
              key={`${p.event_id || p.eventId}-${i}`}
              bet={p}
              onOpenMatch={(bet) => {
                const ev = rows.find((r) => String(r.id) === String(bet.event_id || bet.eventId)) || bet.raw
                if (ev) openMatch(ev)
              }}
            />
          ))}
        </div>
      </section>

      {err && <p className="muted" role="alert">{err}</p>}

      <div className="section-label">Board</div>
      {!loading && !shown.length && (
        <p className="muted">{emptyBoardMessage(rows, activeLeague?.name)}</p>
      )}
      <div className="fixture-table">
        {shown.map((ev) => {
          const open = expanded === ev.id
          const a = open ? analysis : null
          const v = open && a ? rowVerdict(a) : (ev._wc ? rowVerdict(ev) : null)
          const parts = matchScoreParts(ev)
          const odds = ev.odds || {}
          const fromStake = (ev.odds_source || ev.source || '').includes('stake')
          const priced = odds.home && odds.away

          return (
            <article key={ev.id} id={`fixture-${ev.id}`} className={`fixture-row ${open ? 'is-open' : ''} ${ev.status === 'live' ? 'is-live' : ''}`}>
              <button type="button" className="fixture-main" onClick={() => openMatch(ev)}>
                <div className="fixture-time">
                  {ev.status === 'live' ? <span className="live-tag">LIVE</span> : null}
                  <span className="fixture-kick">
                    {ev.status === 'live' && ev.status_detail
                      ? ev.status_detail
                      : (fmtKickoff(ev.kickoff) || 'TBD')}
                  </span>
                  {ev.league && <span className="fixture-comp">{ev.league}</span>}
                </div>
                <div className="fixture-teams">
                  <div className="fixture-side">
                    <TeamLogo key={`h-${ev.id}`} name={ev.home_team} src={ev.home_logo} size={28} sport={group.id} />
                    <span className="fixture-name">{ev.home_team}</span>
                    {parts && <span className="fixture-score">{parts.home}</span>}
                  </div>
                  <div className="fixture-side">
                    <TeamLogo key={`a-${ev.id}`} name={ev.away_team} src={ev.away_logo} size={28} sport={group.id} />
                    <span className="fixture-name">{ev.away_team}</span>
                    {parts && <span className="fixture-score">{parts.away}</span>}
                  </div>
                </div>
                {priced ? (
                  <div className="fixture-odds" onClick={(e) => e.stopPropagation()}>
                    <OddsBtn label="1" value={odds.home} stake={fromStake} onClick={() => parkBoardOdds(ev, 'home')} />
                    {group.id === 'soccer' && (
                      <OddsBtn label="X" value={odds.draw} stake={fromStake} onClick={() => parkBoardOdds(ev, 'draw')} />
                    )}
                    <OddsBtn label="2" value={odds.away} stake={fromStake} onClick={() => parkBoardOdds(ev, 'away')} />
                    {(ev.odds_source === 'model' || (!fromStake && !(ev.odds_source || '').includes('stake') && !(ev.odds_source || '').includes('odds'))) && (
                      <span className="odds-src muted" title="Model fair price until a book quotes">model</span>
                    )}
                  </div>
                ) : (
                  <div className="fixture-odds fixture-odds--empty muted">Pricing…</div>
                )}
                {v && <VerdictBadge verdict={v} />}
              </button>
              {open && a?._wc && (
                <div className="fixture-detail">
                  <MatchSlipPanel
                    slip={a.bet_slip}
                    home={a.home_team}
                    away={a.away_team}
                    fanPrediction={a.fan_prediction}
                    status={a.status}
                    score={a.score}
                    sport={WC_KEY}
                  />
                </div>
              )}
              {open && a && !a._wc && (
                <div className="fixture-detail">
                  <MatchStatsStrip
                    home={ev.home_team}
                    away={ev.away_team}
                    stats={a?.team_stats}
                    probs={probsFromAnalysis(a)}
                  />
                  <AnalysisBrief
                    a={a}
                    analyzing={analyzing}
                    ev={ev}
                    onAdd={addPick}
                    onPark={parkAnalysis}
                  />
                  <MatchSlipPanel
                    slip={a?.bet_slip || null}
                    home={ev.home_team}
                    away={ev.away_team}
                    fanPrediction={a?.web_consensus?.dominant_narrative || null}
                    status={ev.status}
                    score={parts ? `${parts.home}${parts.away ? `-${parts.away}` : ''}` : (ev.score || null)}
                    sport={apiSport}
                  />
                </div>
              )}
              {open && analyzing && !a && (
                <div className="fixture-detail">
                  <p className="muted">Running model…</p>
                </div>
              )}
            </article>
          )
        })}
      </div>
      <LoadMore left={board.length - visible} onClick={() => setVisible((v) => v + PAGE)} />
    </div>
  )
}
