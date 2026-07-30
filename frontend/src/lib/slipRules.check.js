/** ponytail: slip rule self-check — fails if multi/SGM gates regress. */
import { canAddLeg, slipMode, combinedOdds, legsFromBet } from '../lib/slipRules.js'

const a = { eventId: '1', market: 'mw', selection: 'home', odds: 2 }
const b = { eventId: '1', market: 'btts', selection: 'yes', odds: 1.8 }
const c = { eventId: '2', market: 'mw', selection: 'home', odds: 1.5 }
const o15 = { eventId: '1', market: 'over_under_goals', selection: 'over', line: 1.5, odds: 1.4 }
const o25 = { eventId: '1', market: 'over_under_goals', selection: 'over', line: 2.5, odds: 1.9 }
const u25 = { eventId: '1', market: 'over_under_goals', selection: 'under', line: 2.5, odds: 1.9 }

console.assert(canAddLeg([], a).ok)
console.assert(canAddLeg([a], b).ok && canAddLeg([a], b).mode === 'sgm')
console.assert(!canAddLeg([a, b], c).ok)
console.assert(canAddLeg([a], c).ok && canAddLeg([a], c).mode === 'multi')
console.assert(slipMode([a, b]) === 'sgm')
console.assert(combinedOdds([a, b]) === 3.6)
// Different totals lines are both valid on an SGM (was wrongly treated as duplicate)
console.assert(canAddLeg([a, o15], o25).ok)
console.assert(!canAddLeg([o25], u25).ok, 'over vs under same line must conflict')
console.assert(!canAddLeg([o25], { ...o25, odds: 2.1 }).ok, 'exact same pick is duplicate')

const hot = {
  ticket_kind: 'combo',
  market: 'hot_double',
  event_id: '1',
  home_team: 'A',
  away_team: 'B',
  decimal_odds: 3.6,
  label: 'A to win + D to win',
  legs: [
    { event_id: '1', home_team: 'A', away_team: 'B', market: 'match_winner', selection: 'home', label: 'A to win', decimal_odds: 1.8 },
    { event_id: '2', home_team: 'C', away_team: 'D', market: 'match_winner', selection: 'away', label: 'D to win', decimal_odds: 2.0 },
  ],
}
const expanded = legsFromBet(hot, 40)
console.assert(expanded.length === 2, 'hot double expands to 2 legs')
console.assert(expanded[0].eventId !== expanded[1].eventId, 'hot double is a multi across events')
console.assert(Number(expanded[0].odds) > 1 && Number(expanded[1].odds) > 1)
console.log('slip_rules_ok')
