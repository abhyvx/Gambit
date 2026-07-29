import { Link } from 'react-router-dom'
import { useEntryReady } from '../components/EntryScreen'
import './pages.css'

export function PrivacyPage() {
  useEntryReady()
  return (
    <div className="page legal-page">
      <header className="page-header">
        <div>
          <h1>Privacy</h1>
          <p className="subtitle">How GAMBIT handles account and Stake data. Last updated July 2026.</p>
        </div>
      </header>
      <section className="panel legal-body">
        <h2>What we store</h2>
        <ul>
          <li>Account email, display name, and a hashed password (PBKDF2).</li>
          <li>Your betting journal (confirmed slips, imported Stake history, manual entries).</li>
          <li>Optional Stake API token, encrypted at rest on the server.</li>
          <li>Style preferences (goal, risk, bankroll caps) in your browser and/or account journal.</li>
        </ul>
        <h2>What we do not do</h2>
        <ul>
          <li>We are not a bookmaker and do not place bets for you.</li>
          <li>We do not sell your personal data.</li>
          <li>We do not store full Stake passwords. Use an API token you can revoke anytime.</li>
        </ul>
        <h2>Your controls</h2>
        <ul>
          <li>Disconnect Stake or clear the token from Settings / Portfolio.</li>
          <li>Delete your account from Settings — removes account, sessions, and private journal files we hold.</li>
          <li>Confirm-only journals work without connecting Stake at all.</li>
        </ul>
        <h2>Security</h2>
        <p>
          Sessions use bearer tokens. Stake API tokens are sealed with server-side encryption.
          Use a unique password. You are responsible for who can access your device and email.
        </p>
        <p className="muted">
          Questions: treat this as educational software. See also <Link to="/app/legal/terms">Terms</Link>.
        </p>
      </section>
    </div>
  )
}

export function TermsPage() {
  useEntryReady()
  return (
    <div className="page legal-page">
      <header className="page-header">
        <div>
          <h1>Terms</h1>
          <p className="subtitle">Simple rules for using GAMBIT. Last updated July 2026.</p>
        </div>
      </header>
      <section className="panel legal-body">
        <h2>Not a bookmaker</h2>
        <p>
          GAMBIT is analytics software. Outputs are informational, not financial advice,
          and not a guarantee of profit. You place any bets yourself with third parties.
        </p>
        <h2>Age and local law</h2>
        <p>
          You must be 18+ (or the legal age where you live). Gambling is restricted or illegal
          in some places — you are responsible for complying with your local laws.
        </p>
        <h2>Risk</h2>
        <p>
          Betting involves real risk of loss. Only stake what you can afford to lose.
          If gambling is harming you, seek local help (for example BeGambleAware or 1-800-GAMBLER).
        </p>
        <h2>Accounts and Stake tokens</h2>
        <p>
          Keep your password and Stake API token private. You may revoke a Stake token in Stake
          settings at any time. We may suspend accounts that abuse the service.
        </p>
        <h2>No warranty</h2>
        <p>
          The service is provided as-is. Model metrics can change as training and boards update.
          We are not liable for betting losses or decisions made using the app.
        </p>
        <p className="muted">
          See also <Link to="/app/legal/privacy">Privacy</Link>.
        </p>
      </section>
    </div>
  )
}
