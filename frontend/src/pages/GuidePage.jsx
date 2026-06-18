import './pages.css'

export default function GuidePage() {
  return (
    <div className="page guide-page">
      <header className="simple-hero fade-up">
        <span className="page-eyebrow">📖 UNDER THE HOOD</span>
        <h1>How It Works</h1>
        <p className="subtitle">
          The full picture — every step from raw match data to the bets you see, and the actual math behind each one.
        </p>
      </header>

      <section className="guide-section">
        <h2>🧭 The one-paragraph version</h2>
        <p>
          For each World Cup game we estimate the <strong>true chance</strong> of every possible bet using a
          goals model, then nudge it with human/context factors. We pull the <strong>real Stake odds</strong> for
          that game through a real browser, compare our chance against what Stake pays, and keep only bets that are
          both <strong>likely to win (55%+)</strong> and <strong>actually offered on Stake</strong>. Finally we size
          stakes to minimise how often you lose. We never guarantee profit — we tilt the odds in your favour and cut
          obvious traps.
        </p>
      </section>

      <section className="guide-section">
        <h2>🔄 The pipeline (what happens when you open a match)</h2>
        <ol className="pipeline">
          <li><span className="step-n">1</span><div><strong>Live match data</strong> — scores, status, groups, and standings come from ESPN (no key needed).</div></li>
          <li><span className="step-n">2</span><div><strong>Goals model</strong> — a Poisson model turns each team's attack/defence strength into the probability of every scoreline.</div></li>
          <li><span className="step-n">3</span><div><strong>All markets</strong> — from that scoreline grid we derive a probability for ~50 markets (1X2, over/under, BTTS, handicaps, corners, cards, goalscorers, etc.).</div></li>
          <li><span className="step-n">4</span><div><strong>Analyst intuition</strong> — morale, must-win pressure, form vs xG (luck), tactics and public sentiment adjust each probability, capped at ±8%.</div></li>
          <li><span className="step-n">5</span><div><strong>Real Stake odds</strong> — a real browser fetches Stake's live prices for this exact game and re-prices our markets with them.</div></li>
          <li><span className="step-n">6</span><div><strong>De-vig &amp; true edge</strong> — we strip the bookmaker margin from each market to a fair price, then judge every bet on real edge (our chance − fair chance), not phantom value on long-shots.</div></li>
          <li><span className="step-n">7</span><div><strong>Self-learning correction</strong> — the model grades its past predictions against real results and applies what it learned (scoring level, home edge, confidence calibration) before recommending. See the <strong>Model</strong> tab.</div></li>
          <li><span className="step-n">8</span><div><strong>Loss-minimizing plan</strong> — survivors are sized with fractional Kelly into best singles first, with an explicit caution before any parlay.</div></li>
        </ol>
      </section>

      <section className="guide-section">
        <h2>📡 Where the data comes from</h2>
        <dl className="glossary">
          <dt>ESPN (live scores & fixtures)</dt>
          <dd>Real-time scores, kickoff status, groups and standings. Public, no API key, refreshed on demand.</dd>
          <dt>Stake.com (real payouts) — via a real browser</dt>
          <dd>
            Stake sits behind Cloudflare's <em>managed challenge</em>, which blocks plain scripts because it needs
            JavaScript to run. So we drive an actual Chromium browser (Playwright) that passes the challenge once,
            keeps a logged-in session, and runs Stake's internal GraphQL <strong>from inside the page</strong> — exactly
            like your own browser does. That's why a window opens on your machine.
          </dd>
          <dt>DraftKings (fallback)</dt>
          <dd>If we can't confirm the game on Stake, we use live DraftKings prices (via ESPN) and label the plan clearly as an estimate, never pretending it's Stake.</dd>
        </dl>
      </section>

      <section className="guide-section">
        <h2>🧮 The math, step by step</h2>

        <h3>1) Expected goals (how many each team should score)</h3>
        <p>
          Each side's strength is an <strong>Elo rating learned from ~49,000 real international matches</strong>
          (1872–today, recent games weighted most) — so Colombia genuinely outranks Uzbekistan because of
          results, not reputation. The Elo edge is converted to goals using a <strong>goal model fitted on
          ~10,000 recent games</strong>, not hand-typed constants:
        </p>
        <code className="formula">
          elo_edge = home_elo − away_elo (+ small edge for the nominal home side)<br />
          supremacy = a × elo_edge + b   total_goals = c × |elo_edge| + d   (a,b,c,d fitted from data)<br />
          λ_home = (total + supremacy)/2,  λ_away = (total − supremacy)/2
        </code>
        <p className="math-note">For the rare team with too little history, it falls back to a power-rating / xG model.</p>

        <h3>2) The scoreline grid (Poisson)</h3>
        <p>Goals follow a Poisson distribution. The probability of an exact score <code>i–j</code> is each side's Poisson probability multiplied together, over a 0–6 goals grid (then normalised to sum to 1):</p>
        <code className="formula">
          P(score = i–j) = Poisson(i ; λ_home) × Poisson(j ; λ_away)
        </code>

        <h3>3) Turning the grid into market probabilities</h3>
        <p>Every market is just a sum of the right cells in that grid:</p>
        <ul>
          <li><strong>Home win</strong> = sum of cells where i &gt; j · <strong>Draw</strong> = cells where i = j · <strong>Away</strong> = i &lt; j</li>
          <li><strong>Over 2.5</strong> = sum of all cells where i + j &gt; 2.5 (same idea for every line)</li>
          <li><strong>BTTS (yes)</strong> = 1 − P(home 0) − P(away 0) + P(0–0)</li>
          <li><strong>Corners / cards</strong> = separate Poisson models (corners ≈ 10.5 ± pace; cards ≈ 3.8)</li>
        </ul>

        <h3>4) Analyst adjustment (the human layer)</h3>
        <p>
          Pure stats miss context. We add small, capped nudges for: recent luck (form vs xG), morale & momentum,
          tactical matchup, injuries, must-win motivation, and public over-hype. Total adjustment per market is
          clamped to <strong>±8%</strong> so intuition can refine the model but never hijack it. Probabilities are then
          re-normalised so related outcomes still add to 100%.
        </p>

        <h3>5) Fair odds & removing the bookmaker margin (vig)</h3>
        <p>Decimal odds imply a probability, but books pad it so the implied chances add to more than 100%. We strip that padding to get a fair comparison:</p>
        <code className="formula">
          implied probability = 1 / decimal_odds<br />
          fair probability = implied / (sum of all implied in that market)
        </code>

        <h3>6) Expected Value (is the price worth it?)</h3>
        <p>This is the core test. If our chance times the payout beats your stake, it's +EV:</p>
        <code className="formula">
          EV = (our_probability × decimal_odds) − 1
        </code>
        <p className="math-note">Example: 60% chance at 1.95 odds → 0.60 × 1.95 − 1 = <strong>+0.17</strong>, i.e. +17% expected return long-run. EV below the threshold is skipped.</p>

        <h3>7) How much to bet (fractional Kelly)</h3>
        <p>Kelly tells you the bankroll fraction that grows money fastest without ruin. We use a cautious quarter-Kelly:</p>
        <code className="formula">
          b = decimal_odds − 1,  p = our_probability,  q = 1 − p<br />
          Kelly fraction = (p × b − q) / b<br />
          stake = bankroll × Kelly × 0.25  (then hard-capped)
        </code>
        <p className="math-note">
          Caps protect you: max 3% of a full bankroll per bet (or up to 50% of a single-match budget), and lower
          for higher-risk bets. Low confidence halves the stake.
        </p>

        <h3>8) Risk score</h3>
        <p>How shaky is the edge? Driven by confidence and how much the models disagree:</p>
        <code className="formula">
          risk = (1 − confidence) × 0.6 + model_disagreement × 0.4
        </code>
      </section>

      <section className="guide-section">
        <h2>🎭 Game profiling</h2>
        <p>Before picking bets we classify the <em>type</em> of game, so picks fit the match instead of being generic. Each style steers which markets get boosted:</p>
        <dl className="glossary">
          <dt>Dominant favorite</dt><dd>Big rating gap + 55%+ favourite → result/handicap markets on the strong side.</dd>
          <dt>High scoring</dt><dd>Both attacks live (high combined xG) → overs, BTTS, goalscorers.</dd>
          <dt>Low scoring</dt><dd>Tight, cagey → unders, double chance, defensive angles.</dd>
          <dt>Chaotic</dt><dd>Must-win pressure → more cards/corners/goals variance; strict 55%+ only.</dd>
          <dt>Tight</dt><dd>Evenly matched → double chance / draw-no-bet over coin-flip winners.</dd>
          <dt>Balanced</dt><dd>Standard group game → simply the highest-probability bets for these teams.</dd>
        </dl>
      </section>

      <section className="guide-section">
        <h2>🚫 Traps we automatically remove</h2>
        <ul>
          <li><strong>Useless "sure things"</strong> — Over 0.5 / Over 1.5 / Under 4.5+ and anything priced under 1.12. They win ~90% of the time but pay almost nothing.</li>
          <li><strong>25% long shots</strong> — exciting "value" punts below our probability floor. Skipped.</li>
          <li><strong>Lotteries</strong> — exact score and similar are dropped from the main plan.</li>
          <li><strong>Bets not on Stake</strong> — once we confirm the game on Stake, any pick Stake doesn't actually offer (a missing handicap line, a player not listed) is removed so the plan is 100% placeable.</li>
        </ul>
      </section>

      <section className="guide-section">
        <h2>📉 The loss-minimizing plan</h2>
        <p>Among the survivors, three strategies are built. Thresholds are deliberately strict:</p>
        <dl className="glossary">
          <dt>Loss-minimizing (recommended)</dt>
          <dd>2–3 bets across <em>different</em> markets, every leg <strong>55%+</strong> likely. Spreads risk so one miss doesn't wipe the slip. A chunk of budget is always kept unbet.</dd>
          <dt>One best bet</dt>
          <dd>The single highest-confidence pick for the game, sized conservatively.</dd>
          <dt>Smart parlay</dt>
          <dd>Only built when <strong>both legs are 58%+</strong> and the <strong>combined chance is 32%+</strong> — never a random long-shot accumulator.</dd>
        </dl>
        <p className="math-note">
          Each leg shows its win % up front, the source tag <code>🟢 Stake</code> (real odds) or <code>(est.)</code>,
          and worst / likely / best-case payouts so you see the downside before betting.
        </p>
      </section>

      <section className="guide-section">
        <h2>🔬 The ~5,000 factor checks</h2>
        <p>
          For transparency we run a large grid of checks: dozens of base signals (team ratings, xG/xGA, form, morale,
          must-win, fatigue, style, referee tendencies, crowd, group stakes…) cross-referenced against every market
          option. That's where the "thousands of checks" figure comes from — it's the base signals multiplied across
          all the markets, summarised in the <strong>Analysis</strong> tab so you can see what's driving each verdict.
        </p>
      </section>

      <section className="guide-section">
        <h2>📖 Reading a bet card</h2>
        <dl className="glossary">
          <dt>Win % (e.g. "84% likely")</dt><dd>Our model's probability for THIS game — independent of the odds.</dd>
          <dt>Odds (e.g. 1.95x)</dt><dd>Put ₹100, get ₹195 back if it wins. <code>🟢 Stake</code> = real Stake price; <code>(est.)</code> = live-book estimate.</dd>
          <dt>Role (Main / Support / Extra)</dt><dd>Main = anchor pick (biggest stake); Support & Extra spread risk across other markets.</dd>
          <dt>Verdict</dt><dd><strong>BET</strong> = clear edge · <strong>CAUTION</strong> = thin edge, small stake · <strong>SKIP</strong> = no edge, keep your money.</dd>
        </dl>
      </section>

      <section className="guide-section">
        <h2>🛡️ Rules to not lose money</h2>
        <ol>
          <li>Stick to the recommended stakes — they're already capped to protect your bankroll.</li>
          <li>Respect SKIP. No edge means the house wins over time.</li>
          <li>Never chase losses by increasing stake size.</li>
          <li>+EV / "55% likely" means you profit over <em>many</em> bets — any single bet can still lose.</li>
          <li>Only ever bet money you can afford to lose entirely.</li>
        </ol>
        <p className="math-note">
          This is analytical software, not financial advice or a guarantee. Betting carries real risk of loss. If it
          stops being fun or starts costing more than you can afford, stop — and seek help if you need it.
        </p>
      </section>
    </div>
  )
}
