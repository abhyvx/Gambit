import { useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useEntryReady } from '../components/EntryScreen'
import './pages.css'

const BOXES = [
  {
    id: 'box-01_corpus',
    title: '1 · Corpus depth',
    body: (
      <>
        <p>
          How many graded historical + board matches sit under each sport. Larger corpus usually means
          stabler Elo and craft fuel. Esports and off-board sports are excluded on purpose.
        </p>
      </>
    ),
  },
  {
    id: 'box-02_walkforward',
    title: '2 · Walk-forward Elo accuracy',
    body: (
      <>
        <p>
          Hit rate when Elo is updated only on past games and scored on later games. This is a skill check
          on the rating system, not your portfolio PnL.
        </p>
      </>
    ),
  },
  {
    id: 'box-03_board_acc',
    title: '3 · Live-board accuracy',
    body: (
      <>
        <p>
          Finished ESPN / board windows. Thin boards fall back to history accuracy so the cell stays honest
          instead of inventing a huge board sample.
        </p>
      </>
    ),
  },
  {
    id: 'box-04_teams',
    title: '4 · Team Elo coverage',
    body: (
      <p>Count of rated clubs / franchises / nations in the Elo store for each sport.</p>
    ),
  },
  {
    id: 'box-05_players',
    title: '5 · Player Elo coverage',
    body: (
      <p>Player nodes learned from lineups, box scores, and XIs where the fuel exists.</p>
    ),
  },
  {
    id: 'box-06_craft_targets',
    title: '6 · Craft targets',
    body: (
      <>
        <p>
          The bar the craft loop aims at: overall holdout ROI ≥ <strong>25%</strong>, every sport ROI &gt;{' '}
          <strong>0%</strong>, holdout hit rate ≥ <strong>60%</strong>.
        </p>
        <ul>
          <li><strong>Holdout ROI</strong> — paper profit on one frozen match set (same IDs every epoch).</li>
          <li><strong>Holdout hit rate</strong> — share of those tickets that won.</li>
          <li><strong>Gate</strong> — Below target until all bars clear. Never a fake Training spinner for a stored desk.</li>
        </ul>
      </>
    ),
  },
  {
    id: 'box-07_craft_roi_sport',
    title: '7 · Craft ROI by sport',
    body: (
      <>
        <p>
          Per-sport paper ROI from craft holdout when it is positive. If craft for a sport is red and
          close-price pairs are green, the cell shows the paired ROI and notes that craft is gated —
          it does <em>not</em> paint a separate −18% craft line next to a green ROI.
        </p>
      </>
    ),
  },
  {
    id: 'box-08_craft_acc_sport',
    title: '8 · Craft accuracy by sport',
    body: (
      <p>Per-sport holdout hit rate for craft tickets. Target context is the global 60% accuracy bar.</p>
    ),
  },
  {
    id: 'box-09_craft_volume',
    title: '9 · Craft volume',
    body: (
      <p>How many craft tickets graded per sport in the latest meaningful epoch or block.</p>
    ),
  },
  {
    id: 'box-10_craft_equity',
    title: '10 · Self-improvement / equity',
    body: (
      <>
        <p>
          Best-so-far block mean holdout ROI. The curve only rises when a new graded best lands.
          Flat means the champion is already locked at that level — not that learning stopped forever.
        </p>
      </>
    ),
  },
  {
    id: 'box-11_craft_markets',
    title: '11 · Craft markets',
    body: (
      <p>Which market families craft is grading (1X2, totals, handicaps, etc.) and sample depth.</p>
    ),
  },
  {
    id: 'box-12_betting_pairs',
    title: '12 · Betting pairs',
    body: (
      <p>
        Model-fair vs close-price pairs in the evolution store. Used to sanity-check craft and to show
        paired ROI when a craft sport cell is gated.
      </p>
    ),
  },
  {
    id: 'box-13_monthly_roi',
    title: '13 · Monthly ROI',
    body: (
      <p>Month-by-month paper ROI from betting pairs / trends. Gated sports are labeled on the chart.</p>
    ),
  },
  {
    id: 'box-14_yearly_volume',
    title: '14 · Yearly volume',
    body: (
      <p>Ticket or pair counts by year so you can see whether a sport has real sample depth.</p>
    ),
  },
  {
    id: 'box-15_niche_replay',
    title: '15 · Niche replay',
    body: (
      <p>Smaller markets replayed on history. Useful for coverage, not a promise those niches are live-ready.</p>
    ),
  },
  {
    id: 'box-15a_sport_markets',
    title: '15a · Sport markets',
    body: (
      <p>Market coverage rolled up per sport — what lines the desk can price.</p>
    ),
  },
  {
    id: 'box-15b_outcomes',
    title: '15b · Outcomes',
    body: (
      <p>Outcome families the models emit (home/draw/away, overs, spreads, and related).</p>
    ),
  },
  {
    id: 'box-16_calibration',
    title: '16 · Calibration',
    body: (
      <>
        <p>
          Do stated chances match observed hit rates? Brier score (lower better) and reliability buckets
          (predicted % → actual %).
        </p>
      </>
    ),
  },
  {
    id: 'box-17_confidence_tiers',
    title: '17 · Confidence tiers',
    body: (
      <p>Accuracy when the model is more confident. Higher tiers should usually hit more often if calibration is healthy.</p>
    ),
  },
  {
    id: 'box-18_factor_graph',
    title: '18 · Factor graph',
    body: (
      <p>Count of trained graph nodes: teams, players, markets, competitions, market lines.</p>
    ),
  },
  {
    id: 'box-19_stake_volume',
    title: '19 · Stake volume',
    body: (
      <p>Cached Stake handle / bettor depth when the overlay is warm. Empty when Stake is blocked on the host.</p>
    ),
  },
  {
    id: 'box-20_book_depth',
    title: '20 · Book depth',
    body: (
      <p>How many book prices sit behind fixtures — depth for pricing, not a tip sheet.</p>
    ),
  },
  {
    id: 'box-21_soccer_leagues',
    title: '21 · Soccer leagues',
    body: (
      <p>League coverage inside the soccer corpus (top flights vs long tail).</p>
    ),
  },
  {
    id: 'box-21b_bb_ck_fuel',
    title: '21b · Basketball / cricket fuel',
    body: (
      <p>Fuel depth for basketball and cricket corpora that feed Elo and craft.</p>
    ),
  },
  {
    id: 'box-22_epoch_curves',
    title: '22 · Epoch curves',
    body: (
      <p>Per-epoch holdout ROI / accuracy path. Early zeros, then thin or red, then greener after craft fixes.</p>
    ),
  },
  {
    id: 'box-23_sample_health',
    title: '23 · Sample health',
    body: (
      <p>Quick readiness checks: enough corpus, craft volume, and pairs to trust the other boxes.</p>
    ),
  },
  {
    id: 'box-24_takeaways',
    title: '24 · Takeaways',
    body: (
      <p>Short plain-language notes the desk publishes about what improved and what is still gated.</p>
    ),
  },
  {
    id: 'box-25_craft_notes',
    title: '25 · Craft notes',
    body: (
      <p>Operator notes from the craft worker (fuel quirks, sport gates, champion restores).</p>
    ),
  },
]

export default function GuidePage() {
  useEntryReady()
  const { hash } = useLocation()

  useEffect(() => {
    if (!hash) return
    const id = hash.replace(/^#/, '')
    const el = document.getElementById(id)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [hash])

  return (
    <div className="page guide-page">
      <header className="page-header">
        <h1>Guide</h1>
        <p className="subtitle">
          What Gambit is, how tickets are graded, how learning works, and what each Model desk box means.
        </p>
      </header>

      <section className="guide-section panel">
        <h2>In one minute</h2>
        <p>
          Gambit is a research desk for soccer, basketball, and cricket. You get fixtures, prices,
          model chances, and a slip you control. You can keep a private journal of bets you placed
          yourself. The Model page shows how the craft loop is doing on frozen paper tickets.
        </p>
        <p>
          <strong>Gambit is not a bookmaker.</strong> It does not deposit, withdraw, or place bets.
          If you wager, you do that on Stake or another book, under your own account and local laws.
        </p>
        <p className="muted">
          18+ only. See <Link to="/app/legal/terms">Terms</Link> and{' '}
          <Link to="/app/legal/privacy">Privacy</Link>.
        </p>
      </section>

      <section className="guide-section" id="how-recs-work">
        <h2>How we decide what to recommend</h2>
        <ol className="pipeline">
          <li>
            <span className="step-n">1</span>
            <div>
              <strong>Chance (P)</strong>
              {' '}Calibrated model probability the selection wins (Elo + sport models + craft blend).
            </div>
          </li>
          <li>
            <span className="step-n">2</span>
            <div>
              <strong>Odds (O)</strong>
              {' '}Decimal price from Stake, a book cache, or a labeled model fair line.
            </div>
          </li>
          <li>
            <span className="step-n">3</span>
            <div>
              <strong>Edge</strong>
              {' '}P minus the vig-free chance implied by O. Positive edge means the price looks good on paper.
            </div>
          </li>
          <li>
            <span className="step-n">4</span>
            <div>
              <strong>Verdict + stake</strong>
              {' '}Plain language (consider / fair / skip). Optional Kelly fraction sizes a paper stake with hard caps.
              You still place nothing inside Gambit.
            </div>
          </li>
        </ol>
      </section>

      <section className="guide-section" id="how-learning-works">
        <h2>How the model learns</h2>
        <ul>
          <li>
            <strong>Fuel</strong> — finished boards and history for soccer, basketball, and cricket.
          </li>
          <li>
            <strong>Craft epoch</strong> — train on rotating fuel; grade the <em>same</em> frozen holdout IDs every time.
          </li>
          <li>
            <strong>Holdout ROI</strong> — Σ PnL / Σ stake on that frozen book. Hit rate = wins / settled tickets.
          </li>
          <li>
            <strong>Champion policy</strong> — if a run regresses, restore the best graded slice so the public desk does not silently get worse.
          </li>
          <li>
            <strong>Sport gates</strong> — a sport underwater stays off live picks; pairs may still show for honesty.
          </li>
          <li>
            <strong>Self-improvement</strong> — best-so-far block ROI. Rising = new graded best. Flat = champion already locked.
          </li>
          <li>
            <strong>Desk gate</strong> — Below target until overall ROI ≥ 25%, every sport &gt; 0%, accuracy ≥ 60%.
          </li>
        </ul>
        <p>
          Equity and epoch curves on the <Link to="/app/model">Model page</Link> show graded history
          from craft.db when it exists. The README explains the same math in plain English.
        </p>
      </section>

      <section className="guide-section">
        <h2>Typical flow</h2>
        <ol className="pipeline">
          <li>
            <span className="step-n">1</span>
            <div>
              <strong>Open a sport board</strong>
              {' '}Home lists soccer, basketball, and cricket. Pick a league or scroll live / upcoming fixtures.
            </div>
          </li>
          <li>
            <span className="step-n">2</span>
            <div>
              <strong>Read the price source</strong>
              {' '}Stake when the relay is warm, otherwise ESPN/book cache, demo board, or a labeled model estimate.
              Estimated prices are never sold as live book lines.
            </div>
          </li>
          <li>
            <span className="step-n">3</span>
            <div>
              <strong>Open a match</strong>
              {' '}Recs, Build, and Odds tabs share the same fixture. Add legs to your slip. Set your own stake.
            </div>
          </li>
          <li>
            <span className="step-n">4</span>
            <div>
              <strong>Confirm or import</strong>
              {' '}Use Confirm I placed this for upcoming picks, or connect a Stake API token on Portfolio to import history.
              Gambit still does not click Place for you.
            </div>
          </li>
          <li>
            <span className="step-n">5</span>
            <div>
              <strong>Check the Model desk</strong>
              {' '}Holdout ROI, hit rate, per-sport gates, and self-improvement curves. Desk gate stays{' '}
              <em>Below target</em> until the published bar clears. Tap the <strong>i</strong> on any box to jump here.
            </div>
          </li>
        </ol>
      </section>

      <section className="guide-section">
        <h2>Reading a ticket</h2>
        <ul>
          <li><strong>Chance</strong>: model probability that the selection wins.</li>
          <li><strong>Odds</strong>: decimal price from Stake, a book cache, or a labeled estimate.</li>
          <li><strong>Edge</strong>: model chance minus the fair chance implied by that price.</li>
          <li><strong>Verdict</strong>: plain language on whether the price looks worth backing, fair, or a skip.</li>
        </ul>
        <p className="muted">
          Positive edge on paper is not a guarantee. Books move. Injuries land. Variance exists.
        </p>
      </section>

      <section className="guide-section">
        <h2>Odds tab when Stake is offline</h2>
        <p>
          On many cloud hosts Stake blocks datacenter traffic. The Odds tab still tries, in order:
        </p>
        <ol>
          <li>Warm Stake overlay / fixture cache</li>
          <li>ESPN or board 1X2 already on the fixture</li>
          <li>Bundled demo book prices (labeled)</li>
          <li>Gambit model fair 1X2 (labeled)</li>
        </ol>
        <p>
          Always verify the number on Stake.com (or your book) before you risk money.
        </p>
      </section>

      <section className="guide-section" id="model-boxes">
        <h2>Model desk boxes</h2>
        <p>
          Each Model container has an <strong>i</strong> button. It opens this section so you can see what the
          title, numbers, and graphs mean. Hard-refresh if your desk revision looks old — the app rejects stale
          browser caches of older desks.
        </p>
        {BOXES.map((box) => (
          <article key={box.id} id={box.id} className="guide-box-card">
            <h3>{box.title}</h3>
            {box.body}
            <p className="muted">
              <Link to={`/app/model#${box.id}`}>Open on Model →</Link>
            </p>
          </article>
        ))}
      </section>

      <section className="guide-section">
        <h2>Portfolio</h2>
        <ul>
          <li>Sign in so the journal stays private to you.</li>
          <li>Paste a Stake API token from Stake Settings → Security (never your Stake password).</li>
          <li>Or log past bets manually / confirm slips from the board.</li>
          <li>Opt in if you want future graded results to feed learning. Opt out anytime.</li>
        </ul>
      </section>

      <section className="guide-section" id="demo-accounts">
        <h2>Demo accounts</h2>
        <p>
          Boot seeds a few positive journals for demos (not admin). Passwords are fixed:
        </p>
        <ul>
          <li><code>demo.winner@gambit.test</code> / <code>DemoWinner12!</code></li>
          <li><code>demo.builder@gambit.test</code> / <code>DemoBuilder12!</code></li>
          <li><code>demo.learner@gambit.test</code> / <code>DemoLearner12!</code></li>
        </ul>
      </section>

      <section className="guide-section">
        <h2>Rules that do not bend</h2>
        <ul>
          <li>18+ (or the legal age where you live).</li>
          <li>You are responsible for local gambling law.</li>
          <li>Only stake what you can afford to lose.</li>
          <li>Past paper results do not guarantee live results.</li>
          <li>If gambling is hurting you, get help (BeGambleAware, 1-800-GAMBLER, or local services).</li>
        </ul>
      </section>
    </div>
  )
}
