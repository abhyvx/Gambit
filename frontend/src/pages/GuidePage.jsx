import { useEntryReady } from '../components/EntryScreen'
import './pages.css'

export default function GuidePage() {
  useEntryReady()
  return (
    <div className="page guide-page">
      <header className="page-header">
        <h1>How it works</h1>
        <p className="subtitle">
          End-to-end pipeline: data → models → markets → prices → slips → learning.
        </p>
      </header>

      <section className="guide-section">
        <h2>Overview</h2>
        <p>
          Gambit is not a tipster feed. It estimates calibrated win probabilities per market,
          compares them to book prices, and only surfaces tickets when edge and confidence clear
          your style gates. Everything on the Model page is graded on finished results and paired
          closing lines where available.
        </p>
      </section>

      <section className="guide-section">
        <h2>Pipeline (6 stages)</h2>
        <ol className="pipeline">
          <li>
            <span className="step-n">1</span>
            <div>
              <strong>Boards</strong>
              {' '}Live and finished fixtures from ESPN for soccer (EPL, UCL, leagues, internationals),
              basketball (NBA, NCAA M/W, WNBA, FIBA, NBL), and cricket (Tests, ODIs, T20, leagues).
              Odds overlay from Stake relay (cloud), disk cache, or model-fair books when no live price exists.
              Board fetch is cache-first; Odds API credits are not burned on every page load.
            </div>
          </li>
          <li>
            <span className="step-n">2</span>
            <div>
              <strong>Strength models</strong>
              {' '}Walk-forward Elo per sport, merged into a factor graph (teams, players, managers, venues).
              Soccer: football-data.co.uk club CSVs (~1993→), StatsBomb open lineups for player Elo.
              Basketball: FiveThirtyEight <code>nbaallelo</code> (1946-2015) + NCAA/WNBA boards + box scores.
              Cricket: Cricsheet multi-format archives + ESPN board training.
            </div>
          </li>
          <li>
            <span className="step-n">3</span>
            <div>
              <strong>Market map</strong>
              {' '}Soccer: Poisson score grid → 1X2, DNB, BTTS, O/U, Asian handicap, double chance,
              corners, cards. Basketball/cricket: moneyline, spreads, totals (points/runs), not a soccer goals grid.
              Market replay grades popular and niche markets on historical closes.
            </div>
          </li>
          <li>
            <span className="step-n">4</span>
            <div>
              <strong>De-vig / edge</strong>
              {' '}Implied probability = 1/odds after removing book margin. Edge = model_p − fair_p.
              Tickets show p%, market label, decimal odds, stake math. Synthetic/model-fair prices are labeled explicitly.
            </div>
          </li>
          <li>
            <span className="step-n">5</span>
            <div>
              <strong>Sizing & paths</strong>
              {' '}Fractional Kelly against your match budget. Paths: singles, spread (several singles),
              target cashout planner, loss-minimizer, value scan, SGM when Stake board supports it.
              Style (preserve / hit target / value / fun) filters which paths appear.
            </div>
          </li>
          <li>
            <span className="step-n">6</span>
            <div>
              <strong>Learning loop</strong>
              {' '}Market replay grades niches on club CSVs + boards. Betting evolution pairs ~74k historical
              finishes with closing books (soccer B365) or labeled model-fair paper (BB/cricket).
              Craft paper trains on board gems with a frozen holdout (600 matches/sport); champion weights
              restore if holdout regresses. Targets: overall ROI ≥ 25%, each sport ROI &gt; 0, accuracy ≥ 60%.
            </div>
          </li>
        </ol>
      </section>

      <section className="guide-section">
        <h2>Cloud ops (no laptop required)</h2>
        <dl className="glossary">
          <dt>Render</dt>
          <dd>Hosts the web app + API. Craft training does <em>not</em> run here (`CRAFT_DISABLE=1`).</dd>
          <dt>Craft training</dt>
          <dd>GitHub Actions daily. Publishes <code>model-latest</code> release. Redeploy Render after green runs.</dd>
          <dt>Stake relay</dt>
          <dd>GitHub Actions every 15 min. Playwright fetches Stake, POSTs to <code>/api/stake/relay</code>.
            Set your Render URL in <code>deploy/cloud_url.txt</code>.</dd>
          <dt>Holdout</dt>
          <dd>Same match IDs every craft epoch. Retrain refits the whole model, not individual team patches.</dd>
        </dl>
      </section>

      <section className="guide-section">
        <h2>Corpus bounds</h2>
        <dl className="glossary">
          <dt>Soccer clubs</dt>
          <dd>~32 seasons (1993/94→) across major EU divisions on football-data.co.uk, with B365/Avg closes where present.</dd>
          <dt>Basketball franchises</dt>
          <dd>~70 NBA franchise IDs across decades (Elo collapses season teams). Plus NCAA/WNBA/FIBA/NBL boards.</dd>
          <dt>Cricket sides</dt>
          <dd>100+ international/franchise sides across Tests/ODI/T20I in Cricsheet + ESPN boards.</dd>
          <dt>Live boards</dt>
          <dd>Separate from deep history: finished ESPN fixtures for board Elo and craft fuel.</dd>
        </dl>
      </section>

      <section className="guide-section">
        <h2>Reading a ticket</h2>
        <ul>
          <li><strong>p</strong> - calibrated model probability for that selection.</li>
          <li><strong>odds</strong> - decimal from Stake, cached book, or labeled estimate.</li>
          <li><strong>edge</strong> - model_p minus de-vigged implied probability.</li>
          <li><strong>solo net</strong> - P&amp;L if that ticket is the only winner on the card.</li>
          <li><strong>verdict</strong> - BET (clear edge), CAUTION (soft lean), SKIP (no edge).</li>
        </ul>
      </section>

      <section className="guide-section">
        <h2>Model desk containers</h2>
        <p>The Model page shows 20+ containers: corpus depth, board scorecards, craft ROI/accuracy by sport,
          niche market replay, betting evolution trends, calibration buckets, factor graph coverage, Stake book depth,
          and monthly heartbeat. Charts compare <strong>10-epoch blocks</strong>, not live ticks.</p>
      </section>

      <section className="guide-section">
        <h2>Rules</h2>
        <ul>
          <li>18+. Paper unless you place bets yourself.</li>
          <li>Model-fair / synthetic prices are labeled. Do not treat them as closing-line value.</li>
          <li>Past paper ROI on holdout does not guarantee live bankroll performance.</li>
          <li>Odds API: cache-only from Model/craft paths to preserve credits.</li>
        </ul>
      </section>
    </div>
  )
}
