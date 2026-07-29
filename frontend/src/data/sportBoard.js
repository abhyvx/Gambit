/** Sport / league board — top leagues first, rest under Other.
 *
 * Banners: Unsplash License stills (hotlinked) or local sport tiles.
 * Logos: ESPN CDN where available; Wikimedia / Logopedia locals when ESPN has none.
 * No AI-generated photos — missing still → accent gradient + logo only.
 */

export const STYLE_LABELS = {
  preserve: 'Protect bankroll',
  hit_target: 'Hit cashout target',
  value: 'Find edge',
  fun: 'Entertainment',
  low: 'Low risk',
  medium: 'Medium risk',
  high: 'High risk',
  singles: 'Singles',
  spread: 'Several singles',
  mixed: 'Mixed',
  parlays: 'Parlays',
}

/** Unsplash crop helper — distinct photo id per league. */
const U = (id, pos = '50% 45%') => ({
  image: `https://images.unsplash.com/${id}?w=900&h=1200&fit=crop&q=80&auto=format`,
  imagePos: pos,
})

export const SOCCER_TOP5 = [
  'soccer_epl',
  'soccer_uefa_champs_league',
  'soccer_spain_la_liga',
  'soccer_germany_bundesliga',
  'soccer_italy_serie_a',
]

export const SPORT_GROUPS = [
  {
    id: 'soccer',
    name: 'Soccer',
    blurb: 'Live boards worldwide',
    accent: '#14532d',
    image: '/banners/soccer.jpg',
    imagePos: '50% 50%',
    leagues: [
      { key: 'soccer_epl', name: 'Premier League', logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/23.png', top: true, accent: '#3b0a45', ...U('photo-1522778119026-d647f0596c20', '50% 40%') },
      { key: 'soccer_uefa_champs_league', name: 'Champions League', logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/2.png', top: true, accent: '#0b1c3f', ...U('photo-1431324155629-1a6deb1dec8d', '50% 35%') },
      { key: 'soccer_spain_la_liga', name: 'La Liga', logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/15.png', top: true, accent: '#9a3412', ...U('photo-1574629810360-7efbbe195018', '48% 42%') },
      { key: 'soccer_germany_bundesliga', name: 'Bundesliga', logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/10.png', top: true, accent: '#7f1d1d', ...U('photo-1579952363873-27f3bade9f55', '52% 48%') },
      { key: 'soccer_italy_serie_a', name: 'Serie A', logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/12.png', top: true, accent: '#1e3a8a', ...U('photo-1551958219-acbc608c6377', '50% 50%') },
      { key: 'soccer_fifa_world_cup', name: 'World Cup', logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/4.png', top: true, accent: '#064e3b', ...U('photo-1577223625816-7546f13df25d', '50% 38%') },
      { key: 'soccer_other', name: 'Other', logo: null, top: false, accent: '#1a2c38' },
    ],
  },
  {
    id: 'basketball',
    name: 'Basketball',
    blurb: 'NBA, WNBA, NCAA, FIBA',
    accent: '#7c2d12',
    image: '/banners/basketball.jpg',
    imagePos: '50% 45%',
    leagues: [
      { key: 'basketball_nba', name: 'NBA', logo: 'https://a.espncdn.com/i/teamlogos/leagues/500/nba.png', top: true, accent: '#1e3a8a', ...U('photo-1674327175233-51f4d1430eac', '50% 40%') },
      { key: 'basketball_wnba', name: 'WNBA', logo: 'https://a.espncdn.com/i/teamlogos/leagues/500/wnba.png', top: true, accent: '#9a3412', ...U('photo-1574907060871-4555aa8aca75', '55% 48%') },
      { key: 'basketball_ncaab', name: 'NCAA Men', logo: '/logos/ncaa.svg', top: true, accent: '#0c2340', ...U('photo-1504450758481-7338eba7524a', '45% 50%') },
      { key: 'basketball_ncaaw', name: 'NCAA Women', logo: '/logos/ncaa.svg', top: true, accent: '#4c1d95', ...U('photo-1546519638-68e109498ffc', '50% 45%') },
      { key: 'basketball_fiba', name: 'International', logo: 'https://a.espncdn.com/i/teamlogos/leagues/500/fiba.png', top: true, accent: '#0f3d2e', ...U('photo-1533923156502-be31530547c4', '50% 55%') },
      { key: 'basketball_nbl', name: 'NBL', logo: 'https://a.espncdn.com/i/teamlogos/leagues/500/nbl.png', top: true, accent: '#1c1917', ...U('photo-1730315776739-933219f252e0', '40% 45%') },
      { key: 'basketball_all', name: 'All basketball', logo: 'https://a.espncdn.com/i/teamlogos/leagues/500/nba.png', top: false, accent: '#7c2d12', image: '/banners/basketball.jpg', imagePos: '50% 42%' },
    ],
  },
  {
    id: 'cricket',
    name: 'Cricket',
    blurb: 'International + domestic boards',
    accent: '#14532d',
    image: '/banners/cricket.jpg',
    imagePos: '50% 48%',
    // Small set only — empty franchise tabs (IPL/PSL/CPL off-season) deleted.
    leagues: [
      { key: 'cricket_all', name: 'All', logo: 'https://a.espncdn.com/combiner/i?img=/redesign/assets/img/icons/ESPN-icon-cricket.png&w=120&h=120', top: true, accent: '#14532d', image: '/banners/cricket.jpg', imagePos: '50% 45%' },
      { key: 'cricket_international', name: 'International', logo: '/logos/icc.svg', top: true, accent: '#0c4a6e', ...U('photo-1531415074968-036ba1b575da', '50% 40%') },
      { key: 'cricket_domestic', name: 'Domestic', logo: '/logos/cricket.svg', top: true, accent: '#166534', ...U('photo-1540747913346-19e32dc3e97e', '50% 42%') },
    ],
  },
]

const TOP_LEAGUE_HINTS = [
  'premier league', 'english premier', 'uefa champions league', 'uefa.champions',
  'la liga', 'laliga', 'spanish primera', 'bundesliga', 'serie a', 'fifa world', 'world cup',
]

const CRICKET_LEAGUE_KEYS = new Set([
  'cricket_all', 'cricket_international', 'cricket_domestic',
  // Legacy keys still filter if deep-linked
  'cricket_tournaments', 'cricket_ipl', 'cricket_bbl', 'cricket_hundred',
  'cricket_psl', 'cricket_cpl', 'cricket_other', 'cricket_icc_world_cup',
])

export function groupForSportKey(key) {
  if (key === 'soccer_all' || key === 'soccer_other') {
    return SPORT_GROUPS.find((g) => g.id === 'soccer')
  }
  if (key?.startsWith('basketball')) return SPORT_GROUPS.find((g) => g.id === 'basketball')
  if (key?.startsWith('cricket')) return SPORT_GROUPS.find((g) => g.id === 'cricket')
  return SPORT_GROUPS.find((g) => g.leagues.some((l) => l.key === key)) || SPORT_GROUPS[0]
}

export function leagueMeta(key) {
  for (const g of SPORT_GROUPS) {
    const hit = g.leagues.find((l) => l.key === key)
    if (hit) return hit
  }
  if (key === 'soccer_all') return { key, name: 'All soccer', logo: null }
  if (key === 'basketball_all') return { key, name: 'All basketball', logo: null }
  if (key === 'cricket_all') return { key, name: 'All cricket', logo: null }
  return { key, name: humanizeKey(key), logo: null }
}

export function humanizeKey(key) {
  if (!key) return ''
  if (STYLE_LABELS[key]) return STYLE_LABELS[key]
  return String(key).replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function isTopSoccerLeague(leagueName) {
  const blob = String(leagueName || '').toLowerCase()
  if (/(women|women's|womens)/.test(blob)) return false
  return TOP_LEAGUE_HINTS.some((h) => blob.includes(h))
}

/** Live + near-term window. Pad to min upcoming if the window is thin. */
export function inBettingWindow(kickoff, status, { days = 3 } = {}) {
  if (status === 'live') return true
  if (!kickoff) return false
  const d = new Date(kickoff)
  if (Number.isNaN(d.getTime())) return false
  const now = new Date()
  const end = new Date(now)
  end.setUTCDate(end.getUTCDate() + days)
  end.setUTCHours(23, 59, 59, 999)
  return d <= end && d >= new Date(now.getTime() - 4 * 3600_000)
}

export function boardForBetting(rows, { minUpcoming = 24, days = 3, sportId } = {}) {
  const list = rows || []
  const windowDays = sportId === 'basketball' ? 28 : sportId === 'cricket' ? 21 : Math.max(days, 14)
  const live = list.filter((r) => r.status === 'live')
  const up = list
    .filter((r) => r.status === 'upcoming')
    .sort((a, b) => String(a.kickoff || '').localeCompare(String(b.kickoff || '')))
  const inWin = up.filter((r) => inBettingWindow(r.kickoff, r.status, { days: windowDays }))
  let upcoming = inWin.length ? inWin : up
  if (upcoming.length < minUpcoming && up.length > upcoming.length) {
    upcoming = up.slice(0, Math.max(minUpcoming, upcoming.length))
  }
  return [...live, ...upcoming]
}

/** Honest empty-board copy when a league has no live/upcoming fixtures. */
export function emptyBoardMessage(rows, leagueName = 'This board') {
  const list = rows || []
  const live = list.filter((r) => r.status === 'live')
  const up = list.filter((r) => r.status === 'upcoming')
  if (live.length || up.length) return null
  const done = list
    .filter((r) => r.status === 'completed')
    .sort((a, b) => String(b.kickoff || '').localeCompare(String(a.kickoff || '')))
  const label = leagueName || 'This board'
  if (done.length) {
    const last = done[0]
    let when = ''
    try {
      when = last.kickoff
        ? new Date(last.kickoff).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
        : ''
    } catch { /* ignore */ }
    return `${label}: no upcoming fixtures. Last completed match${when ? ` was ${when}` : ''}. Season may be between rounds or finished. Fixtures appear when ESPN or books publish them.`
  }
  return `${label}: no fixtures found right now. Confirmed empty on our scrapers (ESPN + Odds API cache). Tournament may not have started, may be finished, or the schedule is not published yet.`
}

/** Sport-aware live/final score — never split cricket "125/7" on "/". */
export function matchScoreParts(ev) {
  if (!ev || (ev.status !== 'live' && ev.status !== 'completed')) return null
  const h = ev.home_score_display ?? (ev.home_score != null ? String(ev.home_score) : null)
  const a = ev.away_score_display ?? (ev.away_score != null ? String(ev.away_score) : null)
  if (h == null && a == null && !ev.score) return null
  if (h != null || a != null) {
    return { home: h ?? '-', away: a ?? '-', detail: ev.status_detail || '' }
  }
  const raw = String(ev.score || '')
  // Prefer en-dash / em-dash / " vs " - never slash (cricket wickets)
  const m = raw.match(/^(.+?)\s*[–—]\s*(.+)$/) || raw.match(/^(.+?)\s+vs\.?\s+(.+)$/i)
  if (m) return { home: m[1].trim(), away: m[2].trim(), detail: ev.status_detail || '' }
  const hyphen = raw.match(/^(\d+)\s*-\s*(\d+)$/)
  if (hyphen) return { home: hyphen[1], away: hyphen[2], detail: ev.status_detail || '' }
  return { home: raw || '-', away: '', detail: ev.status_detail || '' }
}

/** Resolve fetch sport key — hoop/cricket tabs share one cached board. */
export function fetchSportKey(key) {
  if (key === 'soccer_other') return 'soccer_all'
  if (key?.startsWith('basketball')) return 'basketball_all'
  if (key?.startsWith('cricket')) return 'cricket_all'
  return key
}

/** Client-side league filter after a shared board fetch. */
export function filterRowsForLeague(rows, leagueKey) {
  const list = rows || []
  if (!leagueKey) return list

  if (leagueKey === 'soccer_other') {
    return list.filter((r) => !isTopSoccerLeague(r.league))
  }
  if (leagueKey === 'basketball_all' || leagueKey === 'cricket_all') return list

  if (leagueKey.startsWith('basketball_') && leagueKey !== 'basketball_all') {
    return list.filter((r) => (r.sport_key || '') === leagueKey)
  }

  if (CRICKET_LEAGUE_KEYS.has(leagueKey)) {
    if (leagueKey === 'cricket_all') return list
    // International = bilateral + ICC cups
    if (leagueKey === 'cricket_international' || leagueKey === 'cricket_icc_world_cup') {
      return list.filter((r) => {
        const k = r.sport_key || ''
        return k === 'cricket_international' || k === 'cricket_tournaments'
      })
    }
    // Domestic = franchise / county / everything else
    if (leagueKey === 'cricket_domestic') {
      return list.filter((r) => {
        const k = r.sport_key || ''
        return k !== 'cricket_international' && k !== 'cricket_tournaments'
      })
    }
    return list.filter((r) => (r.sport_key || '') === leagueKey)
  }

  // Named soccer boards: keep matching competition titles when the feed is mixed
  const SOCCER_HINTS = {
    soccer_epl: ['premier league', 'eng.1', 'english premier'],
    soccer_uefa_champs_league: ['uefa champions league', 'uefa.champions', 'champions league'],
    soccer_spain_la_liga: ['laliga', 'la liga', 'spanish primera', 'esp.1'],
    soccer_germany_bundesliga: ['bundesliga', 'ger.1'],
    soccer_italy_serie_a: ['serie a', 'ita.1'],
    soccer_usa_mls: ['mls', 'major league soccer', 'usa.1'],
  }
  if (leagueKey.startsWith('soccer_') && leagueKey !== 'soccer_all' && leagueKey !== 'soccer_fifa_world_cup') {
    // Dedicated ESPN league scrape already scoped — don't over-filter
    if (list.length && list.every((r) => (r.sport_key || '') === leagueKey)) return list
    const hints = SOCCER_HINTS[leagueKey]
    if (!hints) return list
    return list.filter((r) => {
      const blob = `${r.league || ''} ${r.sport_title || ''} ${r.sport_key || ''}`.toLowerCase()
      if (/(women|women's|womens)/.test(blob)) return false
      return hints.some((h) => blob.includes(h))
    })
  }

  if (leagueKey.startsWith('soccer_')) return list
  return list
}
