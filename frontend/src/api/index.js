const API = '/api'

const AUTH_KEY = 'gambit_auth_token'

export function getAuthToken() {
  try {
    return localStorage.getItem(AUTH_KEY) || ''
  } catch {
    return ''
  }
}

export function setAuthToken(token) {
  try {
    if (token) localStorage.setItem(AUTH_KEY, token)
    else localStorage.removeItem(AUTH_KEY)
  } catch { /* private mode */ }
}

function authHeaders(extra = {}) {
  const token = getAuthToken()
  return {
    ...extra,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

function fetchErrorMessage(err, fallback) {
  if (err?.name === 'TimeoutError' || String(err).includes('TimeoutError')) {
    return 'Request timed out. Wait, then click Reload.'
  }
  if (String(err).includes('Failed to fetch')) {
    return 'Could not reach the API. Start ./scripts/run.sh locally, or open your Render URL to wake the free service.'
  }
  return err?.message || fallback
}

export async function checkHealth() {
  const r = await fetch(`${API}/health`, { signal: AbortSignal.timeout(5000) })
  if (!r.ok) throw new Error(`Health ${r.status}`)
  return r.json()
}

export async function fetchCategories() {
  const r = await fetch(`${API}/categories`)
  return r.json()
}

export async function fetchSports(category = null, featured = false) {
  const params = new URLSearchParams()
  if (category) params.set('category', category)
  if (featured) params.set('featured', 'true')
  const r = await fetch(`${API}/sports?${params}`)
  return r.json()
}

const _marketTopCache = new Map()
const MARKET_TOP_TTL_MS = 90_000

export function peekMarketTop(limit = 8) {
  const hit = _marketTopCache.get(String(limit))
  if (hit && Date.now() - hit.ts <= MARKET_TOP_TTL_MS) return hit.data
  return null
}

export async function fetchMarketTop(limit = 8, { force = false } = {}) {
  const key = String(limit)
  if (!force) {
    const hit = _marketTopCache.get(key)
    if (hit && Date.now() - hit.ts < MARKET_TOP_TTL_MS) return hit.data
  }
  const r = await fetch(`${API}/market/top?limit=${limit}`, { signal: AbortSignal.timeout(45000) })
  if (!r.ok) throw new Error(`Market top failed (${r.status})`)
  const data = await r.json()
  _marketTopCache.set(key, { ts: Date.now(), data })
  return data
}

const _eventsCache = new Map()
const EVENTS_TTL_MS = 180_000
const EVENTS_DISK_KEY = 'gambit_events_v1'
const EVENTS_DISK_TTL_MS = 3_600_000  // 1h — Stake-style paint after hard refresh

function _diskLoad(key) {
  try {
    const blob = JSON.parse(localStorage.getItem(EVENTS_DISK_KEY) || '{}')
    const hit = blob[key]
    if (!hit || Date.now() - hit.ts > EVENTS_DISK_TTL_MS) return null
    return hit.data
  } catch {
    return null
  }
}

function _diskSave(key, data) {
  try {
    const blob = JSON.parse(localStorage.getItem(EVENTS_DISK_KEY) || '{}')
    blob[key] = { ts: Date.now(), data }
    const keys = Object.keys(blob)
    if (keys.length > 24) {
      keys
        .sort((a, b) => (blob[a].ts || 0) - (blob[b].ts || 0))
        .slice(0, keys.length - 24)
        .forEach((k) => { delete blob[k] })
    }
    localStorage.setItem(EVENTS_DISK_KEY, JSON.stringify(blob))
  } catch { /* quota / private mode */ }
}

export function peekEventsCache(sport, match = '') {
  const key = `${sport}|${match || ''}`
  const hit = _eventsCache.get(key)
  if (hit && Date.now() - hit.ts <= EVENTS_TTL_MS) return hit.data
  const disk = _diskLoad(key)
  if (disk) {
    _eventsCache.set(key, { ts: Date.now(), data: disk })
    return disk
  }
  return null
}

export async function fetchEvents(sport, match = '', { force = false } = {}) {
  const key = `${sport}|${match || ''}`
  if (!force) {
    const hit = _eventsCache.get(key)
    if (hit && Date.now() - hit.ts < EVENTS_TTL_MS) return hit.data
    const disk = _diskLoad(key)
    if (disk) {
      // Paint immediately from disk; soft-revalidate in background
      _eventsCache.set(key, { ts: Date.now() - EVENTS_TTL_MS + 5_000, data: disk })
      fetchEvents(sport, match, { force: true }).catch(() => {})
      return disk
    }
  }
  const params = new URLSearchParams({ sport })
  if (match) params.set('match', match)
  const r = await fetch(`${API}/events?${params}`, { signal: AbortSignal.timeout(60000) })
  if (!r.ok) throw new Error(`Events failed (${r.status})`)
  const data = await r.json()
  _eventsCache.set(key, { ts: Date.now(), data })
  _diskSave(key, data)
  return data
}

export async function fetchWorldCup({ matchday, eventId, budgetPerMatchInr = 300, targetCashoutInr, includeCompleted = false, forceRefresh = false } = {}) {
  const params = new URLSearchParams({
    budget_per_match_inr: String(budgetPerMatchInr),
    include_completed: String(includeCompleted),
    force_refresh: String(forceRefresh),
  })
  if (targetCashoutInr != null && targetCashoutInr > 0) {
    params.set('target_cashout_inr', String(targetCashoutInr))
  }
  if (matchday !== undefined && matchday !== null) {
    params.set('matchday', String(matchday))
  }
  if (eventId) params.set('event_id', eventId)
  const r = await fetch(`${API}/worldcup?${params}`, { signal: AbortSignal.timeout(45000) })
  if (!r.ok) throw new Error(`World Cup API failed (${r.status})`)
  return r.json()
}

export async function fetchBetBuilder({ home, away, budgetInr = 200, sport } = {}) {
  const params = new URLSearchParams({
    home,
    away,
    budget_inr: String(budgetInr),
  })
  if (sport) params.set('sport', sport)
  const r = await fetch(`${API}/worldcup/bet-builder?${params}`)
  if (!r.ok) throw new Error(`Bet builder failed (${r.status})`)
  return r.json()
}

export async function fetchMatchSlipRefresh({
  home, away, budgetInr = 200, targetCashoutInr = 1000, refreshStake = true, sport,
  goal, risk, structure,
} = {}) {
  const params = new URLSearchParams({
    home,
    away,
    budget_inr: String(budgetInr),
    target_cashout_inr: String(targetCashoutInr),
    refresh_stake: String(refreshStake),
  })
  if (sport) params.set('sport', sport)
  if (goal) params.set('goal', goal)
  if (risk) params.set('risk', risk)
  if (structure) params.set('structure', structure)
  const r = await fetch(`${API}/worldcup/match-slip?${params}`, { signal: AbortSignal.timeout(90000) })
  if (!r.ok) {
    const detail = await r.text().catch(() => '')
    throw new Error(detail?.slice(0, 160) || `Match slip refresh failed (${r.status})`)
  }
  return r.json()
}

export async function fetchHitTarget({
  home, away, budgetInr = 200, targetCashoutInr = 1000,
  goal, risk, structure, sport,
} = {}) {
  const params = new URLSearchParams({
    home,
    away,
    budget_inr: String(budgetInr),
    target_cashout_inr: String(targetCashoutInr),
  })
  if (goal) params.set('goal', goal)
  if (risk) params.set('risk', risk)
  if (structure) params.set('structure', structure)
  if (sport) params.set('sport', sport)
  const r = await fetch(`${API}/worldcup/hit-target?${params}`, { signal: AbortSignal.timeout(90000) })
  if (!r.ok) {
    const detail = await r.text().catch(() => '')
    throw new Error(detail?.slice(0, 120) || `Hit target failed (${r.status})`)
  }
  return r.json()
}

export async function refreshStakeOverlay() {
  const r = await fetch(`${API}/stake/refresh`, { method: 'POST', signal: AbortSignal.timeout(90000) })
  if (!r.ok) throw new Error(`Stake refresh failed (${r.status})`)
  return r.json()
}

export async function connectStakeSession() {
  const r = await fetch(`${API}/stake/connect`, { method: 'POST', signal: AbortSignal.timeout(300000) })
  if (!r.ok) {
    const raw = await r.text().catch(() => '')
    throw new Error(raw?.slice(0, 160) || `Stake connect failed (${r.status})`)
  }
  return r.json()
}

export async function fetchPortfolioState() {
  const r = await fetch(`${API}/portfolio`, {
    headers: authHeaders(),
    signal: AbortSignal.timeout(20000),
  })
  if (!r.ok) throw new Error(`Portfolio state failed (${r.status})`)
  return r.json()
}

export async function updatePortfolioPrivacy(payload) {
  const r = await fetch(`${API}/portfolio/privacy`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error(`Portfolio privacy update failed (${r.status})`)
  return r.json()
}

export async function connectPortfolioSession() {
  const r = await fetch(`${API}/portfolio/connect`, {
    method: 'POST',
    headers: authHeaders(),
    signal: AbortSignal.timeout(300000),
  })
  if (!r.ok) throw new Error(`Portfolio connect failed (${r.status})`)
  return r.json()
}

export async function disconnectPortfolioSession() {
  const r = await fetch(`${API}/portfolio/disconnect`, {
    method: 'POST',
    headers: authHeaders(),
  })
  if (!r.ok) throw new Error(`Portfolio disconnect failed (${r.status})`)
  return r.json()
}

export async function refreshPortfolioSnapshot() {
  const r = await fetch(`${API}/portfolio/refresh`, {
    method: 'POST',
    headers: authHeaders(),
    signal: AbortSignal.timeout(120000),
  })
  if (!r.ok) {
    const raw = await r.text()
    let msg = `Portfolio refresh failed (${r.status})`
    try {
      const data = JSON.parse(raw)
      msg = data.detail || msg
    } catch {
      if (raw) msg = raw
    }
    throw new Error(msg)
  }
  return r.json()
}

export async function connectStakeApiToken(token) {
  const r = await fetch(`${API}/portfolio/stake-token`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ token }),
    signal: AbortSignal.timeout(120000),
  })
  if (!r.ok) {
    const raw = await r.text()
    let msg = `Stake token connect failed (${r.status})`
    try {
      const data = JSON.parse(raw)
      if (data?.detail) msg = typeof data.detail === 'string' ? data.detail : msg
    } catch { /* ignore */ }
    throw new Error(msg)
  }
  return r.json()
}

export async function confirmPortfolioSlip({ legs, multiStake, multiOdds } = {}) {
  const r = await fetch(`${API}/portfolio/confirm-slip`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      legs: legs || [],
      multi_stake: multiStake != null && multiStake !== '' ? Number(multiStake) : null,
      multi_odds: multiOdds != null ? Number(multiOdds) : null,
    }),
    signal: AbortSignal.timeout(30000),
  })
  if (!r.ok) {
    const raw = await r.text()
    let msg = `Could not confirm slip (${r.status})`
    try {
      const data = JSON.parse(raw)
      if (data?.detail) msg = typeof data.detail === 'string' ? data.detail : msg
    } catch { /* ignore */ }
    throw new Error(msg)
  }
  return r.json()
}

export async function addManualPortfolioBet(payload) {
  const r = await fetch(`${API}/portfolio/bets`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(30000),
  })
  if (!r.ok) {
    const raw = await r.text()
    let msg = `Could not save bet (${r.status})`
    try {
      const data = JSON.parse(raw)
      if (data?.detail) msg = typeof data.detail === 'string' ? data.detail : msg
    } catch { /* ignore */ }
    throw new Error(msg)
  }
  return r.json()
}

export async function updatePortfolioBetResult(betId, result, payout = null) {
  const r = await fetch(`${API}/portfolio/bets/${encodeURIComponent(betId)}/result`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ result, payout }),
    signal: AbortSignal.timeout(20000),
  })
  if (!r.ok) throw new Error(`Could not update bet (${r.status})`)
  return r.json()
}

export async function authSignup({ email, password, name }) {
  const r = await fetch(`${API}/auth/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, name }),
  })
  if (!r.ok) {
    const raw = await r.json().catch(() => ({}))
    throw new Error(raw.detail || `Sign up failed (${r.status})`)
  }
  const data = await r.json()
  setAuthToken(data.token)
  return data
}

export async function authLogin({ email, password }) {
  const r = await fetch(`${API}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!r.ok) {
    const raw = await r.json().catch(() => ({}))
    throw new Error(raw.detail || `Sign in failed (${r.status})`)
  }
  const data = await r.json()
  setAuthToken(data.token)
  return data
}

export async function authLogout() {
  try {
    await fetch(`${API}/auth/logout`, { method: 'POST', headers: authHeaders() })
  } catch { /* ignore */ }
  setAuthToken('')
}

export async function fetchAuthMe() {
  const r = await fetch(`${API}/auth/me`, { headers: authHeaders() })
  if (!r.ok) return { user: null }
  return r.json()
}

export async function recordSlipLegs(legs) {
  const r = await fetch(`${API}/slip/record`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ legs: legs || [] }),
  })
  if (!r.ok) throw new Error(`Slip record failed (${r.status})`)
  return r.json()
}

export async function settleSlipLeg({ id, won, sport }) {
  const r = await fetch(`${API}/slip/settle`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, won: Boolean(won), sport }),
  })
  if (!r.ok) throw new Error(`Slip settle failed (${r.status})`)
  return r.json()
}

export { fetchErrorMessage }

export async function fetchStakeOdds({ home, away, budgetInr = 200 } = {}) {
  const params = new URLSearchParams({
    home,
    away,
    budget_inr: String(budgetInr),
  })
  const r = await fetch(`${API}/worldcup/stake-odds?${params}`, { signal: AbortSignal.timeout(90000) })
  if (!r.ok) throw new Error(`Stake odds failed (${r.status})`)
  return r.json()
}

export async function fetchModelReport({ retrain = false } = {}) {
  const params = new URLSearchParams({ retrain: String(retrain) })
  const timeout = retrain ? 300000 : 20000
  const r = await fetch(`${API}/model/report?${params}`, { signal: AbortSignal.timeout(timeout) })
  if (!r.ok) throw new Error(`Model report failed (${r.status})`)
  return r.json()
}

export async function fetchModelScorecard({ refresh = false } = {}) {
  const params = new URLSearchParams({ refresh: String(refresh) })
  const r = await fetch(`${API}/model/scorecard?${params}`, { signal: AbortSignal.timeout(30000) })
  if (!r.ok) throw new Error(`Model scorecard failed (${r.status})`)
  return r.json()
}

export async function fetchModelActivity(limit = 40) {
  const r = await fetch(`${API}/model/activity?limit=${limit}`, { signal: AbortSignal.timeout(15000) })
  if (!r.ok) throw new Error(`Activity log failed (${r.status})`)
  return r.json()
}

export async function fetchPaperBook() {
  const r = await fetch(`${API}/model/paper`, { signal: AbortSignal.timeout(15000) })
  if (!r.ok) throw new Error(`Paper book failed (${r.status})`)
  return r.json()
}

const _insightsCache = { ts: 0, data: null }
const INSIGHTS_CLIENT_TTL_MS = 120_000
const INSIGHTS_DISK_KEY = 'gambit_insights_v1'

export function peekModelInsights() {
  if (_insightsCache.data && Date.now() - _insightsCache.ts <= INSIGHTS_CLIENT_TTL_MS) {
    return _insightsCache.data
  }
  try {
    const raw = JSON.parse(sessionStorage.getItem(INSIGHTS_DISK_KEY) || 'null')
    if (raw?.data && Date.now() - raw.ts <= INSIGHTS_CLIENT_TTL_MS) {
      _insightsCache.ts = raw.ts
      _insightsCache.data = raw.data
      return raw.data
    }
  } catch { /* private mode */ }
  return null
}

export async function fetchCraftProgress() {
  const r = await fetch(`${API}/model/craft`, { signal: AbortSignal.timeout(15000) })
  if (!r.ok) throw new Error(`Craft progress failed (${r.status})`)
  return r.json()
}

export async function fetchModelInsights({ force = false } = {}) {
  if (!force) {
    const hit = peekModelInsights()
    if (hit) return hit
  }
  const r = await fetch(`${API}/model/insights`, { signal: AbortSignal.timeout(90000) })
  if (!r.ok) throw new Error(`Model insights failed (${r.status})`)
  const data = await r.json()
  _insightsCache.ts = Date.now()
  _insightsCache.data = data
  try {
    sessionStorage.setItem(INSIGHTS_DISK_KEY, JSON.stringify({ ts: _insightsCache.ts, data }))
  } catch { /* quota */ }
  return data
}

export async function runPaperCycle({
  trainWalkforward = true,
  placeLive = true,
  bankroll = 10000,
  matchBudget = 200,
  maxGames = 60,
  untilRoi = false,
  targetRoi = 0.25,
  targetAcc = 0.55,
  maxEpochs = 0, // 0 = unlimited until targets hit
} = {}) {
  const params = new URLSearchParams({
    train_walkforward: String(trainWalkforward),
    place_live: String(placeLive),
    bankroll: String(bankroll),
    match_budget: String(matchBudget),
    max_games: String(maxGames),
    until_roi: String(untilRoi),
    target_roi: String(targetRoi),
    target_acc: String(targetAcc),
    max_epochs: String(maxEpochs),
  })
  const r = await fetch(`${API}/model/paper/cycle?${params}`, {
    method: 'POST',
    // Unlimited craft can run a long time — keep the request alive
    signal: AbortSignal.timeout(untilRoi ? 7_200_000 : 300000),
  })
  if (!r.ok) throw new Error(`Paper cycle failed (${r.status})`)
  return r.json()
}

export async function fetchAnalysis({
  sport,
  match,
  eventId,
  bankroll = 300,
  goal = 'preserve',
  risk = 'medium',
  structure = 'spread',
  targetCashoutInr,
} = {}) {
  const params = new URLSearchParams({
    sport,
    bankroll: String(bankroll),
    goal,
    risk,
    structure,
  })
  if (match) params.set('match', match)
  if (eventId) params.set('event_id', eventId)
  if (targetCashoutInr != null) params.set('target_cashout_inr', String(targetCashoutInr))
  const r = await fetch(`${API}/analyze?${params}`, { signal: AbortSignal.timeout(60000) })
  if (!r.ok) throw new Error(`Analysis failed (${r.status})`)
  return r.json()
}

export async function fetchBettorStyleCatalog() {
  const r = await fetch(`${API}/bettor-style`, { signal: AbortSignal.timeout(10000) })
  if (!r.ok) throw new Error(`Style catalog failed (${r.status})`)
  return r.json()
}
