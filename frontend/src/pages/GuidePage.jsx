import { useEntryReady } from '../components/EntryScreen'
import './pages.css'

export default function GuidePage() {
  useEntryReady()
  return (
    <div className="page guide-page">
      <header className="page-header">
        <h1>Guide</h1>
        <p className="subtitle">How Gambit builds and grades bets.</p>
      </header>

      <section className="guide-section">
        <h2>Flow</h2>
        <ol className="pipeline">
          <li>
            <span className="step-n">1</span>
            <div>
              <strong>Boards</strong>
              {' '}Live and finished fixtures for soccer, basketball, and cricket.
            </div>
          </li>
          <li>
            <span className="step-n">2</span>
            <div>
              <strong>Strength</strong>
              {' '}Team and player ratings from history and finished boards.
            </div>
          </li>
          <li>
            <span className="step-n">3</span>
            <div>
              <strong>Markets</strong>
              {' '}Match result, totals, handicaps, and other core markets.
            </div>
          </li>
          <li>
            <span className="step-n">4</span>
            <div>
              <strong>Prices</strong>
              {' '}Stake when available, otherwise cached books or model prices (labeled).
            </div>
          </li>
          <li>
            <span className="step-n">5</span>
            <div>
              <strong>Slips</strong>
              {' '}Sized tickets from your style and budget.
            </div>
          </li>
          <li>
            <span className="step-n">6</span>
            <div>
              <strong>Learning</strong>
              {' '}Grades finished results. Craft paper aims for 25% ROI with each sport above 0.
            </div>
          </li>
        </ol>
      </section>

      <section className="guide-section">
        <h2>Reading a ticket</h2>
        <ul>
          <li><strong>Chance</strong>: model probability for that pick.</li>
          <li><strong>Odds</strong>: decimal price from Stake, a book, or a labeled estimate.</li>
          <li><strong>Edge</strong>: model chance minus the fair book chance.</li>
          <li><strong>Verdict</strong>: BET, CAUTION, or SKIP.</li>
        </ul>
      </section>

      <section className="guide-section">
        <h2>Rules</h2>
        <ul>
          <li>18+. You place your own bets.</li>
          <li>Estimated prices are labeled. Do not treat them as live book lines.</li>
          <li>Past paper results do not guarantee live results.</li>
        </ul>
      </section>
    </div>
  )
}
