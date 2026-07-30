import { Link } from 'react-router-dom'
import { useEntryReady } from '../components/EntryScreen'
import './pages.css'

export default function GuidePage() {
  useEntryReady()
  return (
    <div className="page guide-page">
      <header className="page-header">
        <h1>Guide</h1>
        <p className="subtitle">
          What Gambit is, how to read a board and a ticket, and what the Model desk numbers mean.
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
              <em>Below target</em> until the published bar clears.
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

      <section className="guide-section">
        <h2>Model desk words</h2>
        <ul>
          <li>
            <strong>Holdout ROI</strong>: paper profit on one frozen set of matches. Same games every run,
            so you can tell if learning moved.
          </li>
          <li>
            <strong>Holdout hit rate</strong>: share of those tickets that won. Target is 60%+.
          </li>
          <li>
            <strong>Desk gate</strong>: clears only when overall ROI is at least 25%, every sport is above 0%,
            and hit rate clears 60%. Until then you will see Below target, not a fake Training spinner.
          </li>
          <li>
            <strong>Self-improvement / equity</strong>: best-so-far block ROI. Rising means the graded best
            improved. Flat means the champion is already locked at that level.
          </li>
        </ul>
        <p className="muted">
          Hard-refresh if the desk revision looks old. The app rejects stale browser caches of older desks.
        </p>
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
