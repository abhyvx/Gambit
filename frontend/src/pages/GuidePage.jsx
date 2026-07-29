import { useEntryReady } from '../components/EntryScreen'
import './pages.css'

export default function GuidePage() {
  useEntryReady()
  return (
    <div className="page guide-page">
      <header className="page-header">
        <h1>How it works</h1>
        <p className="subtitle">
          Pipeline, data bounds, and pricing math — no marketing copy.
        </p>
      </header>

      <section className="guide-section">
        <h2>Pipeline</h2>
        <ol className="pipeline">
          <li>
            <span className="step-n">1</span>
            <div>
              <strong>Boards</strong>
              {' '}ESPN fixtures/scores for soccer, basketball, cricket. Odds overlay from disk cache
              (Odds API / Stake session when available). Board fetch is cache-first; live Odds API is not
              burned on every paint.
            </div>
          </li>
          <li>
            <span className="step-n">2</span>
            <div>
              <strong>Strength models</strong>
              {' '}Walk-forward Elo by sport. Soccer: club CSVs (football-data ~1993→) + internationals +
              StatsBomb open lineups for player Elo. Basketball: FiveThirtyEight <code>nbaallelo</code>
              (1946–2015 franchises) + 2010–2024 box scores. Cricket: Cricsheet Tests/ODI/T20I + leagues.
            </div>
          </li>
          <li>
            <span className="step-n">3</span>
            <div>
              <strong>Market map</strong>
              {' '}Soccer: Poisson score grid → 1X2, DNB, BTTS, OU, AH, corners/cards. Basketball/cricket:
              moneyline + OU + spreads (points/runs), not a soccer goals grid.
            </div>
          </li>
          <li>
            <span className="step-n">4</span>
            <div>
              <strong>De-vig / edge</strong>
              {' '}Implied = 1/odds after removing book margin. Edge = model_p − fair_p. Tickets show
              p%, market, odds, stake math — not narrative prose.
            </div>
          </li>
          <li>
            <span className="step-n">5</span>
            <div>
              <strong>Sizing</strong>
              {' '}Fractional Kelly against match budget. Paths: target / loss-min / singles / value / SGM.
            </div>
          </li>
          <li>
            <span className="step-n">6</span>
            <div>
              <strong>Learning loop</strong>
              {' '}Market replay grades niches (result/BTTS/totals). Betting evolution pairs finishes with
              closing books (soccer B365/Avg) or labeled model-fair paper (BB/cricket). Craft paper grades
              board gems; target is a small unit edge (~5%), not a fantasy +25% vs closes.
            </div>
          </li>
        </ol>
      </section>

      <section className="guide-section">
        <h2>Corpus bounds</h2>
        <dl className="glossary">
          <dt>Soccer clubs</dt>
          <dd>~32 seasons (1993/94→) across major EU divisions on football-data.co.uk, with B365/Avg closes where present.</dd>
          <dt>Basketball “teams”</dt>
          <dd>
            ~70 NBA <em>franchises</em> across decades (Elo collapses season teams into franchise IDs).
            Game count is 60k+, not “70 games”.
          </dd>
          <dt>Cricket sides</dt>
          <dd>100+ international/franchise sides across formats in Cricsheet zips (multi-decade).</dd>
          <dt>Live boards</dt>
          <dd>Separate from history: finished ESPN fixtures used for board Elo / craft — volume depends on what’s cached.</dd>
        </dl>
      </section>

      <section className="guide-section">
        <h2>Reading a ticket</h2>
        <ul>
          <li><strong>p</strong> — calibrated model probability.</li>
          <li><strong>odds</strong> — decimal from book or labeled estimate.</li>
          <li><strong>edge</strong> — model_p − de-vigged implied.</li>
          <li><strong>solo net</strong> — P&amp;L if that ticket is the only winner on the card.</li>
        </ul>
      </section>

      <section className="guide-section">
        <h2>Rules</h2>
        <ul>
          <li>18+. Paper unless you place yourself.</li>
          <li>Model-fair / synthetic prices are labeled — do not treat them as CLV.</li>
          <li>Past paper ROI ≠ live bankroll.</li>
        </ul>
      </section>
    </div>
  )
}
