import { useEffect, useMemo, useState } from 'react'
import { fetchBetBuilder } from '../api/index'
import { formatINR, useBankroll } from '../context/BankrollContext'

const keyOf = (o) => `${o.market}|${o.selection}|${o.line ?? ''}`

const TONE_CLASS = { good: 'tone-good', warn: 'tone-warn', bad: 'tone-bad', neutral: 'tone-neutral' }
const SHOW_BADGE = new Set(['great', 'good', 'avoid', 'trap', 'longshot'])

// Stake's real soccer tab order. `id` is the backend category that feeds the tab
// (`All` shows everything; `Main` is the curated headline board, like Stake).
const STAKE_TABS = [
  { id: 'All', label: 'All' },
  { id: 'Main', label: 'Main' },
  { id: 'Total Goals', label: 'Goals' },
  { id: 'Halves', label: 'Halves' },
  { id: 'Both Teams To Score', label: 'Both Teams To Score' },
  { id: 'Handicap', label: 'Handicap' },
  { id: 'Corners', label: 'Corners' },
  { id: 'Cards', label: 'Bookings' },
  { id: 'Goalscorers', label: 'Player' },
  { id: 'Correct Score', label: 'Correct Score' },
  { id: 'Combos', label: 'Multi-Bet' },
  { id: 'Match Result', label: 'Match Result' },
]

const MAIN_MARKET_RE = /(match winner|^1x2|1×2|double chance|draw no bet|both teams to score|total goals|asian handicap)/i

const ISO2 = {
  Ghana: 'gh', Panama: 'pa', Colombia: 'co', Uzbekistan: 'uz', Argentina: 'ar', Brazil: 'br',
  France: 'fr', England: 'gb-eng', Spain: 'es', Germany: 'de', Portugal: 'pt', Netherlands: 'nl',
  Belgium: 'be', Croatia: 'hr', Italy: 'it', Mexico: 'mx', USA: 'us', Canada: 'ca', Japan: 'jp',
  'South Korea': 'kr', 'Korea Republic': 'kr', Morocco: 'ma', Senegal: 'sn', Uruguay: 'uy',
  Norway: 'no', Switzerland: 'ch', Denmark: 'dk', Ecuador: 'ec', Australia: 'au', Iran: 'ir',
  'Saudi Arabia': 'sa', Qatar: 'qa', Poland: 'pl', Serbia: 'rs', Sweden: 'se', Austria: 'at',
  Turkey: 'tr', Scotland: 'gb-sct', Wales: 'gb-wls', 'Ivory Coast': 'ci', Algeria: 'dz',
  Ghana_: 'gh', Nigeria: 'ng', Egypt: 'eg', Cameroon: 'cm', Tunisia: 'tn', Peru: 'pe',
  Chile: 'cl', Paraguay: 'py', 'Costa Rica': 'cr', 'South Africa': 'za', 'DR Congo': 'cd',
  'Czech Republic': 'cz', Bosnia: 'ba', Iraq: 'iq', Jordan: 'jo', 'Curaçao': 'cw',
  'New Zealand': 'nz', Jamaica: 'jm', Honduras: 'hn',
}

function flagEmoji(_name) {
  return ''
}

function fmtKickoff(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const mon = d.toLocaleString('en-GB', { day: '2-digit', month: 'short' }).toUpperCase()
    const time = d.toLocaleString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false })
    return `${mon} | ${time}`
  } catch { return '' }
}

// ── Stake selection logic: contradictions on the goal/result family ──
function parseScore(o) {
  if (o._cat !== 'Correct Score') return null
  const m = `${o.label || o.selection || ''}`.match(/(\d+)\s*[-:]\s*(\d+)/)
  return m ? { h: +m[1], a: +m[2] } : null
}
function goalPredicate(o) {
  const { market, selection, line } = o
  if (market === 'match_winner') {
    if (selection === 'home') return (h, a) => h > a
    if (selection === 'draw') return (h, a) => h === a
    if (selection === 'away') return (h, a) => a > h
  }
  if (market === 'double_chance') {
    if (selection === 'home_draw') return (h, a) => h >= a
    if (selection === 'draw_away') return (h, a) => a >= h
    if (selection === 'home_away') return (h, a) => h !== a
  }
  if (market === 'draw_no_bet') {
    if (selection === 'home') return (h, a) => h > a
    if (selection === 'away') return (h, a) => a > h
  }
  if (market === 'over_under_goals' && line != null) {
    if (selection === 'over') return (h, a) => h + a > line
    if (selection === 'under') return (h, a) => h + a < line
  }
  if (market === 'btts') {
    if (selection === 'yes') return (h, a) => h >= 1 && a >= 1
    if (selection === 'no') return (h, a) => h === 0 || a === 0
  }
  const cs = parseScore(o)
  if (cs) return (h, a) => h === cs.h && a === cs.a
  return null
}
function satisfiable(pa, pb) {
  for (let h = 0; h <= 8; h++) for (let a = 0; a <= 8; a++) if (pa(h, a) && pb(h, a)) return true
  return false
}

export default function BetBuilder({ home, away, budget, sport }) {
  const { perMatchBudget } = useBankroll()
  const baseBudget = Math.round(budget || perMatchBudget || 300)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [picksMap, setPicksMap] = useState({})
  const [slipTab, setSlipTab] = useState('single')
  const [multiStake, setMultiStake] = useState(baseBudget)
  const [singleStakes, setSingleStakes] = useState({})
  const [onlyValue, setOnlyValue] = useState(false)
  const [openMarkets, setOpenMarkets] = useState({})
  const [search, setSearch] = useState('')
  const [activeTab, setActiveTab] = useState('All')

  useEffect(() => {
    let cancelled = false
    setLoading(true); setError(null); setData(null); setPicksMap({}); setSingleStakes({}); setActiveTab('All')
    fetchBetBuilder({ home, away, budgetInr: baseBudget, sport })
      .then((d) => {
        if (cancelled) return
        setData(d)
        // Stake shows everything expanded - no dropdowns. Open every market.
        const open = {}
        ;(d.categories || []).forEach((c) => c.markets.forEach((m) => { open[m.market_label] = true }))
        setOpenMarkets(open)
      })
      .catch((e) => { if (!cancelled) setError(e?.message || 'Could not load the bet menu.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [home, away, baseBudget, sport])

  // Flatten categories → markets (each its own accordion, Stake-style).
  const allMarkets = useMemo(() => {
    if (!data?.categories) return []
    return data.categories.flatMap((c) => c.markets.map((m) => ({ ...m, _cat: c.category })))
  }, [data])

  const allOutcomes = useMemo(
    () => allMarkets.flatMap((m) => m.outcomes.map((o) => ({ ...o, market_label: m.market_label, _cat: m._cat }))),
    [allMarkets],
  )
  const outcomeByKey = useMemo(() => {
    const map = {}
    allOutcomes.forEach((o) => { map[keyOf(o)] = o })
    return map
  }, [allOutcomes])

  const picks = useMemo(() => Object.values(picksMap), [picksMap])

  // Outcomes that would contradict the current slip (Stake greys these out).
  const blockedKeys = useMemo(() => {
    const set = new Set()
    const sel = picks.map((p) => ({ p, pred: goalPredicate(p) })).filter((x) => x.pred)
    if (!sel.length) return set
    allOutcomes.forEach((o) => {
      const k = keyOf(o)
      if (picksMap[k]) return
      const pred = goalPredicate(o)
      if (!pred) return
      for (const s of sel) {
        if (s.p.market_label === o.market_label) continue // same market → swap, not block
        if (!satisfiable(pred, s.pred)) { set.add(k); break }
      }
    })
    return set
  }, [picks, allOutcomes, picksMap])

  const toggle = (raw) => {
    const o = outcomeByKey[keyOf(raw)] || raw
    const k = keyOf(o)
    if (blockedKeys.has(k)) return
    setPicksMap((prev) => {
      const next = { ...prev }
      if (next[k]) { delete next[k]; return next }
      // Radio swap: only one selection per market accordion.
      if (o.market_label) {
        Object.keys(next).forEach((kk) => { if (next[kk].market_label === o.market_label) delete next[kk] })
      }
      next[k] = o
      return next
    })
    setSingleStakes((prev) => {
      if (prev[k] != null) return prev
      const n = Object.keys(prev).length + 1
      const share = Math.max(10, Math.round(baseBudget / Math.max(n, 1) / 10) * 10)
      return { ...prev, [k]: share }
    })
  }

  const setLegStake = (k, val) => setSingleStakes((prev) => ({ ...prev, [k]: val }))

  useEffect(() => { if (picks.length < 2 && slipTab === 'multi') setSlipTab('single') }, [picks.length, slipTab])

  const singleRows = picks.map((p) => {
    const k = keyOf(p)
    const s = Number(singleStakes[k] ?? baseBudget) || 0
    return { p, k, stake: s, ret: s * p.odds }
  })
  const singleTotalStake = singleRows.reduce((a, r) => a + r.stake, 0)
  const singleTotalReturn = singleRows.reduce((a, r) => a + r.ret, 0)

  const ms = Number(multiStake) || 0
  const combinedOdds = picks.reduce((a, p) => a * p.odds, 1)
  const ratedAll = picks.length > 0 && picks.every((p) => p.our_probability != null)
  const combinedChance = ratedAll ? picks.reduce((a, p) => a * p.our_probability, 1) : null
  const multiReturn = ms * combinedOdds

  if (loading) {
    return (
      <div className="sk slip-tab-content">
        <div className="stake-skeleton">
          <div className="stake-skel-head"><div className="spinner small" /><p>Loading every Stake bet for {home} vs {away}…</p></div>
          <div className="skeleton sk-line" /><div className="skeleton sk-line short" /><div className="skeleton sk-block" />
        </div>
      </div>
    )
  }
  if (error || !data?.available) {
    return (
      <div className="sk slip-tab-content">
        <div className="stake-fallback">
          <span className="fallback-icon" aria-hidden></span>
          <h5>Bet menu unavailable</h5>
          <p>{error || data?.reason || 'Could not build the bet menu for this match.'}</p>
        </div>
      </div>
    )
  }

  const read = data.analyst_read
  const recommended = data.recommended_picks || []
  const wp = data.win_probability || {}
  const recKeys = new Set(recommended.map((p) => keyOf(p)))

  // Tabs in Stake's order, only those with markets present.
  const presentCats = new Set((data.categories || []).map((c) => c.category))
  const tabs = STAKE_TABS.filter((t) => t.id === 'All' || t.id === 'Main' || presentCats.has(t.id))

  // "Main" = Stake's curated headline board: full-match result/goals/BTTS/handicap,
  // never team-specific or half markets.
  const teamRe = new RegExp(
    `${(data.home || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}|${(data.away || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`,
    'i',
  )
  const isMainMarket = (m) => {
    const lbl = m.market_label || ''
    if (teamRe.test(lbl) || /half/i.test(lbl)) return false
    return MAIN_MARKET_RE.test(lbl)
  }

  const q = search.trim().toLowerCase()
  const visibleMarkets = allMarkets
    .filter((m) => (activeTab === 'All' ? true : activeTab === 'Main' ? isMainMarket(m) : m._cat === activeTab))
    .map((m) => ({
      ...m,
      outcomes: m.outcomes.filter((o) => {
        if (onlyValue && !['great', 'good'].includes(o.verdict?.tier)) return false
        if (q && !(`${m.market_label} ${o.label} ${m._cat}`.toLowerCase().includes(q))) return false
        return true
      }),
    }))
    .filter((m) => m.outcomes.length)

  function renderOutcomeBtn(o, extra = '') {
    const eo = { ...o, market_label: o.market_label, _cat: o._cat }
    const k = keyOf(o)
    const selected = !!picksMap[k]
    const blocked = blockedKeys.has(k)
    const v = o.verdict || {}
    const rated = SHOW_BADGE.has(v.tier)
    const toneCls = v.tier && v.tier !== 'unrated' ? (TONE_CLASS[v.tone] || '') : ''
    const rec = recKeys.has(k)
    const oddsOnly = extra.includes('odds-only')
    const our = o.our_probability_pct
    const edge = o.edge_pct
    const edgeCls = edge == null ? '' : edge >= 1.5 ? 'pos' : edge <= -2 ? 'neg' : 'mid'
    return (
      <button
        key={k}
        className={`sk-out ${extra} ${toneCls} ${selected ? 'sel' : ''} ${blocked ? 'blocked' : ''} ${rec ? 'rec' : ''}`}
        onClick={() => toggle(eo)}
        disabled={blocked}
        title={blocked ? "Conflicts with a bet already in your slip - can't combine these." : (v.blurb || o.label || '')}
      >
        {!oddsOnly && (
          <span className="sk-out-main">
            <span className="sk-out-label">{rec && <span className="sk-star"></span>}{o.label}</span>
            {our != null && (
              <span className="sk-out-read">
                <span className="sk-read-prob">{our}% model</span>
                {edge != null && <span className={`sk-read-edge ${edgeCls}`}>{edge > 0 ? '+' : ''}{edge}%</span>}
              </span>
            )}
          </span>
        )}
        <span className="sk-out-right">
          {rated && <span className={`sk-out-badge ${TONE_CLASS[v.tone]}`}>{v.icon}</span>}
          {oddsOnly && our != null && <span className="sk-cell-prob">{our}%</span>}
          {oddsOnly && rec && <span className="sk-star"></span>}
          <span className="sk-out-odds">{o.odds}</span>
        </span>
      </button>
    )
  }

  function renderMarket(m) {
    const isOpen = q ? true : (openMarkets[m.market_label] ?? false)
    const outs = m.outcomes.map((o) => ({ ...o, market_label: m.market_label, _cat: m._cat }))

    // Over/Under detection that also catches team totals where the selection is
    // "Over 0.5"/"Under 0.5" rather than a bare "over"/"under".
    const ouSide = (o) => {
      const s = `${o.selection || ''}`.toLowerCase()
      if (s === 'over' || s === 'under') return s
      const lab = `${o.label || o.selection || ''}`.toLowerCase().trim()
      if (lab.startsWith('over')) return 'over'
      if (lab.startsWith('under')) return 'under'
      return null
    }
    const ouLine = (o) => {
      if (o.line != null) return o.line
      const mm = `${o.label || o.selection || ''}`.match(/-?\d+(?:\.\d+)?/)
      return mm ? parseFloat(mm[0]) : null
    }
    const isOU = outs.length > 1 && outs.every((o) => ouSide(o)) && outs.some((o) => ouLine(o) != null)
    const isHcp = !isOU && m.outcomes[0]?.market === 'asian_handicap'
      && outs.length > 2 && outs.every((o) => o.selection === 'home' || o.selection === 'away')

    let body
    if (isOU) {
      const byLine = {}
      outs.forEach((o) => { const L = ouLine(o) ?? '?'; (byLine[L] = byLine[L] || {})[ouSide(o)] = o })
      const lines = Object.keys(byLine).sort((a, b) => parseFloat(a) - parseFloat(b))
      body = (
        <div className="sk-ou">
          <div className="sk-ou-head"><span>Line</span><span>Over</span><span>Under</span></div>
          {lines.map((L) => (
            <div className="sk-ou-row threecol" key={L}>
              <span className="sk-ou-line">{L}</span>
              {byLine[L].over ? renderOutcomeBtn(byLine[L].over, 'sk-ou-cell odds-only') : <span className="sk-ou-empty" />}
              {byLine[L].under ? renderOutcomeBtn(byLine[L].under, 'sk-ou-cell odds-only') : <span className="sk-ou-empty" />}
            </div>
          ))}
        </div>
      )
    } else if (isHcp) {
      const byLine = {}
      outs.forEach((o) => { const L = Math.abs(o.line ?? 0); (byLine[L] = byLine[L] || {})[o.selection] = o })
      const lines = Object.keys(byLine).sort((a, b) => parseFloat(a) - parseFloat(b))
      body = (
        <div className="sk-ou">
          <div className="sk-ou-head"><span>Line</span><span>{data.home}</span><span>{data.away}</span></div>
          {lines.map((L) => (
            <div className="sk-ou-row threecol" key={L}>
              <span className="sk-ou-line">±{L}</span>
              {byLine[L].home ? renderOutcomeBtn(byLine[L].home, 'sk-ou-cell odds-only') : <span className="sk-ou-empty" />}
              {byLine[L].away ? renderOutcomeBtn(byLine[L].away, 'sk-ou-cell odds-only') : <span className="sk-ou-empty" />}
            </div>
          ))}
        </div>
      )
    } else {
      body = <div className="sk-outcomes">{outs.map((o) => renderOutcomeBtn(o))}</div>
    }

    return (
      <div key={m.market_label} className={`sk-acc ${isOpen ? 'open' : ''}`}>
        <button className="sk-acc-head" onClick={() => setOpenMarkets((p) => ({ ...p, [m.market_label]: !isOpen }))}>
          <span className="sk-acc-title">{m.market_label}</span>
          <span className="sk-acc-chev">{isOpen ? '⌃' : '⌄'}</span>
        </button>
        {isOpen && <div className="sk-acc-body">{body}</div>}
      </div>
    )
  }

  return (
    <div className="sk slip-tab-content" key="build">
      <div className="sk-grid">
        {/* ============ LEFT: the board ============ */}
        <div className="sk-board">
          {/* group tabs */}
          <div className="sk-tabs">
            {tabs.map((t) => (
              <button key={t.id} className={`sk-tab ${activeTab === t.id ? 'active' : ''}`} onClick={() => setActiveTab(t.id)}>
                {t.label}
              </button>
            ))}
          </div>

          {/* search */}
          <div className="sk-search">
            <span className="sk-search-ico">⌕</span>
            <input placeholder="Search" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>

          {/* Total odds bar (Stake-style) */}
          <div className="sk-totalbar">
            <span className="sk-totalbar-label">Total Odds: <strong className="green">{picks.length ? combinedOdds.toFixed(2) : 'n/a'}</strong></span>
            <div className="sk-totalbar-actions">
              <button className="sk-clear" disabled={!picks.length} onClick={() => { setPicksMap({}); setSingleStakes({}) }}>Clear All</button>
              <span className="sk-addbet">{picks.length} selected</span>
            </div>
          </div>

          {data.source !== 'stake' && (
            <div className="builder-warn" style={{ margin: '0 0 12px' }}>
              Stake hasn't opened the full live board for this game yet - these are our estimated prices.
            </div>
          )}

          {/* markets */}
          <div className="sk-markets">
            {visibleMarkets.length === 0
              ? <p className="muted" style={{ padding: '16px 4px' }}>No markets match your filter.</p>
              : visibleMarkets.map(renderMarket)}
          </div>
        </div>

        {/* ============ RIGHT: match panel + slip ============ */}
        <div className="sk-side">
          {/* match header */}
          <div className="sk-matchcard">
            <div className="sk-mc-head">
              <div className="sk-mc-team"><span className="sk-flag">{flagEmoji(data.home)}</span><span>{data.home}</span></div>
              <div className="sk-mc-mid">{fmtKickoff(data.kickoff) || (data.group ? data.group : 'Match')}</div>
              <div className="sk-mc-team away"><span>{data.away}</span><span className="sk-flag">{flagEmoji(data.away)}</span></div>
            </div>
            {(wp.home || wp.away) && (
              <div className="sk-winprob">
                <div className="sk-winprob-label">Win probability <span className="muted-inline">(our model)</span></div>
                <div className="sk-winprob-bar">
                  <div className="wp home" style={{ width: `${Math.round((wp.home || 0) * 100)}%` }} />
                  <div className="wp draw" style={{ width: `${Math.round((wp.draw || 0) * 100)}%` }} />
                  <div className="wp away" style={{ width: `${Math.round((wp.away || 0) * 100)}%` }} />
                </div>
                <div className="sk-winprob-pcts">
                  <span className="home">{Math.round((wp.home || 0) * 100)}% {data.home}</span>
                  <span className="draw">{Math.round((wp.draw || 0) * 100)}% Draw</span>
                  <span className="away">{Math.round((wp.away || 0) * 100)}% {data.away}</span>
                </div>
              </div>
            )}
          </div>

          {/* Market tags + addable picks - no narrative prose */}
          {(read?.tags?.length > 0 || recommended.length > 0) && (
            <div className="analyst">
              {read?.tags?.length > 0 && (
                <div className="analyst-tags">{read.tags.map((t) => <span key={t} className="atag">{t}</span>)}</div>
              )}
              {data.easy_money?.length > 0 && (
                <div className="easy-money-box is-lock-tier">
                  <h5>High probability</h5>
                  <ul className="easy-money-list">
                    {data.easy_money.slice(0, 4).map((p, i) => (
                      <li key={`easy-${i}`}>
                        <strong>{p.label}</strong>
                        {p.odds != null && <span className="easy-odds"> @ {p.odds}</span>}
                        {p.our_probability_pct != null && <span> · {p.our_probability_pct}%</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {recommended.length > 0 ? (
                <>
                  <div className="analyst-picks-label">Picks - tap to add</div>
                  <div className="analyst-picks">
                    {recommended.map((p) => {
                      const sel = !!picksMap[keyOf(p)]
                      const blocked = blockedKeys.has(keyOf(p))
                      return (
                        <button key={keyOf(p)} className={`apick ${sel ? 'sel' : ''} ${blocked ? 'blocked' : ''}`}
                          disabled={blocked} onClick={() => toggle(p)}>
                          <div className="apick-top"><span className="apick-tag">{p.tag}</span><span className="apick-odds">{p.odds}x</span></div>
                          {p.market_label && <div className="apick-mkt">{p.market_label}</div>}
                          <div className="apick-label">{p.label}{p.our_probability_pct != null && <span className="apick-pct">{p.our_probability_pct}%</span>}</div>
                          <div className="apick-add">{blocked ? 'conflicts with slip' : sel ? ' in slip' : '+ add'}</div>
                        </button>
                      )
                    })}
                  </div>
                </>
              ) : (
                <div className="no-bet">
                  <strong>No edge on this board.</strong>
                  <span>Nothing clears the price filter.</span>
                </div>
              )}
              {data.best_parlay && (
                <div className="smart-multi">
                  <div className="smart-multi-head">
                    <span>Optional multi</span>
                    <span className="smart-multi-odds">{data.best_parlay.combined_odds}x</span>
                  </div>
                  <div className="smart-multi-legs">
                    {data.best_parlay.legs.map((l, i) => (
                      <span key={i} className="smart-leg">{l.label}<small>{l.odds}x</small></span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* bet slip */}
          <div className="builder-slip">
            <div className="builder-slip-head">
              <h5>Bet slip {picks.length > 0 && <span className="slip-count">{picks.length}</span>}</h5>
              {picks.length > 0 && <button className="slip-clear" onClick={() => { setPicksMap({}); setSingleStakes({}) }}>Clear all</button>}
            </div>

            {picks.length === 0 ? (
              <p className="muted builder-empty">No bets yet. Tap any odds and they'll show here.</p>
            ) : (
              <>
                <div className="slip-mode-tabs">
                  <button className={slipTab === 'single' ? 'active' : ''} onClick={() => setSlipTab('single')}>
                    Singles<small>{picks.length} separate bet{picks.length > 1 ? 's' : ''}</small>
                  </button>
                  <button className={slipTab === 'multi' ? 'active' : ''} disabled={picks.length < 2}
                    onClick={() => picks.length >= 2 && setSlipTab('multi')}
                    title={picks.length < 2 ? 'Add 2+ bets to make a multi' : ''}>
                    Multi<small>{picks.length < 2 ? 'add 2+ bets' : 'all must win'}</small>
                  </button>
                </div>

                {slipTab === 'single' && (
                  <div className="slip-singles">
                    {singleRows.map(({ p, k, stake, ret }) => (
                      <div key={k} className="slip-leg">
                        <div className="slip-leg-top">
                          <span className="slip-leg-name">{p.label}</span>
                          <button className="bp-remove" onClick={() => toggle(p)} aria-label="Remove">×</button>
                        </div>
                        <div className="slip-leg-sub">
                          {SHOW_BADGE.has(p.verdict?.tier) && <span className={`chip-tag ${TONE_CLASS[p.verdict?.tone]}`}>{p.verdict?.icon} {p.verdict?.label}</span>}
                          <span className="slip-leg-odds">{p.odds}x</span>
                        </div>
                        <div className="slip-leg-stake">
                          <label>Bet ₹</label>
                          <input type="number" min="10" step="10" value={stake} onChange={(e) => setLegStake(k, e.target.value)} />
                          <span className="slip-leg-ret">wins <strong className="green">{formatINR(Math.round(ret))}</strong></span>
                        </div>
                      </div>
                    ))}
                    <div className="slip-totals">
                      <div><span>Total you bet</span><strong>{formatINR(Math.round(singleTotalStake))}</strong></div>
                      <div><span>Back if all win</span><strong className="green">{formatINR(Math.round(singleTotalReturn))}</strong></div>
                    </div>
                  </div>
                )}

                {slipTab === 'multi' && picks.length >= 2 && (
                  <div className="slip-multi">
                    <div className="slip-multi-legs">
                      {picks.map((p) => (
                        <div key={keyOf(p)} className="builder-pick">
                          {SHOW_BADGE.has(p.verdict?.tier) && <span className="bp-verdict">{p.verdict?.icon}</span>}
                          <span className="bp-label">{p.label}</span>
                          <span className="bp-odds">{p.odds}x</span>
                          <button className="bp-remove" onClick={() => toggle(p)} aria-label="Remove">×</button>
                        </div>
                      ))}
                    </div>
                    <div className="slip-leg-stake">
                      <label>Bet ₹</label>
                      <input type="number" min="10" step="10" value={multiStake} onChange={(e) => setMultiStake(e.target.value)} />
                    </div>
                    <div className="slip-totals">
                      <div><span>Combined odds</span><strong>{combinedOdds.toFixed(2)}x</strong></div>
                      <div><span>Chance all {picks.length} win</span><strong>{combinedChance != null ? `${Math.round(combinedChance * 100)}%` : 'n/a'}</strong></div>
                      <div><span>Back if it hits</span><strong className="green">{formatINR(Math.round(multiReturn))}</strong></div>
                    </div>
                    <p className="slip-multi-note">All {picks.length} legs must win or you lose the whole bet.</p>
                    {data.parlay_caution && <p className="slip-multi-caution"> {data.parlay_caution}</p>}
                  </div>
                )}

                <a className="stake-open-btn" href={data.stake_url} target="_blank" rel="noreferrer">Place these on Stake →</a>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
