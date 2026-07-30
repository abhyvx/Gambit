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
          <p className="subtitle">How Gambit handles account and Stake data. Last updated July 2026.</p>
        </div>
      </header>
      <section className="panel legal-body">
        <h2>Who we are</h2>
        <p>
          Gambit is analytics software for sports boards and model grades. It is not a gambling operator,
          payment processor, or financial advisor.
        </p>

        <h2>What we store</h2>
        <ul>
          <li>Account email, display name, and a hashed password (PBKDF2-HMAC-SHA256).</li>
          <li>Session tokens so you can stay signed in on your devices.</li>
          <li>Your betting journal (confirmed slips, imported Stake history, manual entries) when you use Portfolio.</li>
          <li>Optional Stake API token, sealed at rest when <code>GAMBIT_SECRETS_KEY</code> is configured on the host.</li>
          <li>Style preferences (goal, risk, bankroll caps) in your browser and/or account journal.</li>
          <li>Optional learning opt-in flags and graded feedback derived from bets you chose to sync.</li>
        </ul>

        <h2>What we do not do</h2>
        <ul>
          <li>We are not a bookmaker and do not place bets for you.</li>
          <li>We do not sell your personal data.</li>
          <li>We do not ask for or store your Stake password. Use a revocable API token only.</li>
          <li>We do not require Stake connect to use boards, the slip, or confirm-only journals.</li>
        </ul>

        <h2>Your controls</h2>
        <ul>
          <li>Disconnect Stake or clear the token from Account / Portfolio at any time.</li>
          <li>Revoke the token inside Stake Settings → Security so the old credential stops working.</li>
          <li>Delete your account from Settings. That removes account, sessions, and private journal files we hold on this host.</li>
          <li>Turn learning opt-in off whenever you want.</li>
        </ul>

        <h2>Security</h2>
        <p>
          Sessions use bearer tokens. Stake API tokens should be sealed with server-side encryption when the host
          is configured correctly. Use a unique password. You are responsible for who can access your device,
          email, and Stake account. No system is perfectly secure; report issues to the operator of your deployment.
        </p>

        <h2>Third parties</h2>
        <p>
          Boards and prices may come from ESPN, Stake, The Odds API (if configured), or model estimates.
          Those services have their own terms. Gambit does not control their retention of public sports data.
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
          <h1>Terms of use</h1>
          <p className="subtitle">Rules for using Gambit. Last updated July 2026.</p>
        </div>
      </header>
      <section className="panel legal-body">
        <h2>Agreement</h2>
        <p>
          By using Gambit you agree to these Terms and the <Link to="/app/legal/privacy">Privacy</Link> notice.
          If you do not agree, do not use the software.
        </p>

        <h2>Not a bookmaker / not advice</h2>
        <p>
          Gambit is analytics and journaling software. Outputs (probabilities, edges, ROI, hit rates, verdicts,
          slips, and portfolio stats) are informational only. They are not financial, investment, or gambling advice,
          and not a guarantee of profit or loss. You alone decide whether to bet, and you place any bets yourself
          with third-party operators.
        </p>

        <h2>Age and local law</h2>
        <p>
          You must be 18 or older, or the legal age for gambling-related content where you live, whichever is higher.
          Online gambling is restricted or illegal in many jurisdictions. You are solely responsible for complying
          with the laws that apply to you. Do not use Gambit to break those laws.
        </p>

        <h2>Risk and responsible use</h2>
        <p>
          Betting involves a real risk of losing money. Only stake what you can afford to lose.
          If gambling is harming you or someone you know, seek local help (for example BeGambleAware,
          Gamblers Anonymous, or 1-800-GAMBLER in the US).
        </p>

        <h2>Accounts and Stake tokens</h2>
        <p>
          Keep your password and any Stake API token private. Create tokens you can revoke. Never share account
          access. We may suspend or delete accounts that abuse the service, attempt unauthorized access,
          scrape in a way that harms the host, or use the software to facilitate illegal activity.
        </p>

        <h2>Price sources and accuracy</h2>
        <p>
          Prices may come from Stake, ESPN, cached books, demo boards, or model fair estimates. Source labels
          matter. Model and demo prices are not live book lines. Data can be delayed, incomplete, or wrong.
          Always confirm numbers on your book before risking money.
        </p>

        <h2>No warranty</h2>
        <p>
          THE SOFTWARE IS PROVIDED &quot;AS IS&quot; AND &quot;AS AVAILABLE&quot;, WITHOUT WARRANTIES OF ANY KIND,
          EXPRESS OR IMPLIED, INCLUDING MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT.
          We do not warrant uninterrupted uptime, unbroken integrations with Stake or other third parties,
          or that model metrics will meet any target.
        </p>

        <h2>Limitation of liability</h2>
        <p>
          TO THE MAXIMUM EXTENT PERMITTED BY LAW, THE OPERATORS AND CONTRIBUTORS OF GAMBIT ARE NOT LIABLE FOR
          ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, OR ANY LOSS OF PROFITS, DATA,
          GOODWILL, OR BETTING LOSSES, ARISING FROM YOUR USE OF THE SOFTWARE OR RELIANCE ON ITS OUTPUTS,
          EVEN IF ADVISED OF THE POSSIBILITY. OUR TOTAL LIABILITY FOR ANY CLAIM RELATING TO THE SOFTWARE
          IS LIMITED TO THE GREATER OF (A) THE AMOUNT YOU PAID US FOR THE SOFTWARE IN THE THREE MONTHS BEFORE
          THE CLAIM (OFTEN ZERO FOR A FREE HOSTED DEMO) OR (B) FIFTY US DOLLARS (US$50).
        </p>

        <h2>Indemnity</h2>
        <p>
          You agree to defend and indemnify the operators and contributors of Gambit against claims, damages,
          losses, and expenses (including reasonable legal fees) arising from your misuse of the software,
          your betting activity, your violation of these Terms, or your violation of applicable law.
        </p>

        <h2>Third-party services</h2>
        <p>
          Stake, ESPN, The Odds API, hosting providers, and other integrations are independent. Their outages,
          blocks, terms, and fees are outside our control. Links to third-party sites do not mean endorsement.
        </p>

        <h2>Acceptable use</h2>
        <ul>
          <li>No attempts to bypass security, age gates, or access other users&apos; journals.</li>
          <li>No use of the software to operate an unlicensed bookmaking business.</li>
          <li>No automated abuse that threatens the stability of a shared host.</li>
          <li>No uploading of unlawful content.</li>
        </ul>

        <h2>Changes</h2>
        <p>
          We may update these Terms. Continued use after an update means you accept the revised Terms.
          The date at the top of this page is the latest revision.
        </p>

        <h2>Contact</h2>
        <p>
          For the deployment you are using, contact the operator who runs that host. This repository is software;
          a public demo may be operated by volunteers or individuals with no paid support obligation.
        </p>

        <p className="muted">
          See also <Link to="/app/legal/privacy">Privacy</Link> and the in-app <Link to="/app/guide">Guide</Link>.
        </p>
      </section>
    </div>
  )
}
