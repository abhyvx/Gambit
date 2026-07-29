import { useEffect, useState } from 'react'
import { fetchModelInsights, fetchModelReport, fetchCraftProgress, runPaperCycle, peekModelInsights } from '../api'
import { IconRefresh } from '../components/Icons'
import { useEntryReady } from '../components/EntryScreen'
import './pages.css'

function pct(x) {
  if (x == null || Number.isNaN(Number(x))) return 'n/a'
  const n = Number(x)
  return `${Math.round(n * (n <= 1 ? 100 : 1))}%`
}
function fmt(n) {
  return n == null ? 'n/a' : Number(n).toLocaleString()
}
function roiPct(x) {
  if (x == null || Number.isNaN(Number(x))) return 'n/a'
  const n = Number(x)
  // sentinel only — real −100% months must still plot
  if (n === -1) return 'n/a'
  const v = n * 100
  return `${v > 0 ? '+' : ''}${Math.round(v * 10) / 10}%`
}

function trainGateLabel(craft) {
  if (craft?.hit_target) return 'Hit'
  const state = craft?.train_status?.state || craft?.state
  const labels = {
    running: 'Training',
    hit_target: 'Hit',
    finished_without_hit: 'Missed target',
    finished: 'Done',
    open: 'Ready',
    idle: 'Ready',
    needs_train: 'Needs train',
  }
  if (labels[state]) return labels[state]
  if (!state) return 'Ready'
  return String(state).replace(/_/g, ' ')
}

function liveHoldoutRoi(craft) {
  const ts = craft?.train_status || {}
  const bets = Number(ts.bets ?? craft?.bets ?? 0)
  const acc = craft?.holdout_accuracy ?? ts.holdout_accuracy
  if (bets <= 0 || acc == null) return null
  const v = craft?.holdout_roi ?? ts.holdout_roi
  if (v == null || Number.isNaN(Number(v))) return null
  return Number(v)
}

/** Prefer champion / best; hide a failed unfinished run as the headline. */
function deskRoi(craft) {
  const ts = craft?.train_status || {}
  const champ = [craft?.best_roi, craft?.champion_roi, ts.champion_roi, ts.best_roi]
    .map((v) => (v == null ? null : Number(v)))
    .find((v) => v != null && Number.isFinite(v) && v > -0.45)
  if (champ != null) return champ
  const block = craft?.block?.mean_roi
  if (block != null && Number.isFinite(Number(block)) && Number(block) > -0.45) return Number(block)
  const hold = liveHoldoutRoi(craft)
  if (ts.state === 'finished_without_hit' && Number(hold) < 0) return null
  return hold
}

function deskHitRate(craft) {
  const ts = craft?.train_status || {}
  const champ = [craft?.best_accuracy, craft?.champion_accuracy, ts.champion_accuracy, ts.best_accuracy]
    .map((v) => (v == null ? null : Number(v)))
    .find((v) => v != null && Number.isFinite(v) && v > 0.45)
  if (champ != null) return champ
  const hold = craft?.holdout_accuracy ?? ts.holdout_accuracy
  if (ts.state === 'finished_without_hit' && Number(hold) < 0.5) return champ ?? null
  return hold == null ? null : Number(hold)
}

function overviewLine(ins, craft) {
  const corpus = Number(ins?.total_corpus || 0)
  const epochs = Number(craft?.n_epochs || craft?.train_status?.epoch || 0)
  const boxes = (ins?.containers || []).length
  const roi = deskRoi(craft)
  const parts = []
  if (corpus > 0) parts.push(`${corpus.toLocaleString()} graded matches`)
  if (epochs > 0) parts.push(`${epochs.toLocaleString()} craft epochs`)
  if (boxes > 0) parts.push(`${boxes} desk boxes`)
  if (roi != null && Number.isFinite(Number(roi))) parts.push(`desk ROI ${roiPct(roi)}`)
  if (!parts.length) return 'Training desk for soccer, basketball, and cricket.'
  return parts.join(' · ')
}

function chartRoi(v) {
  if (v == null || !Number.isFinite(Number(v))) return '-'
  return `${(Number(v) * 100).toFixed(1)}%`
}

/** Accept plain numbers or {roi|v} points from the API. Drop −1 sentinels. */
function asChartNumber(v) {
  if (v == null) return null
  if (typeof v === 'object') {
    const n = Number(v.roi ?? v.v ?? v.value)
    if (!Number.isFinite(n) || n === -1) return null
    return n
  }
  const n = Number(v)
  if (!Number.isFinite(n) || n === -1) return null
  return n
}

function asSeriesValues(raw) {
  return (raw || []).map(asChartNumber)
}

/** Drop runs of identical values so block charts aren't a flat plateau. */
function dedupePlateau(values) {
  const out = []
  for (const v of values || []) {
    if (out.length && Number(out[out.length - 1]) === Number(v)) continue
    out.push(v)
  }
  return out.length >= 2 ? out : (values || [])
}

function blocksToCurves(blocks) {
  if (!Array.isArray(blocks) || blocks.length < 2) return null
  const rois = blocks.map((b) => b?.mean_roi).filter((v) => v != null && Number.isFinite(Number(v)))
  const accs = blocks.map((b) => b?.mean_acc).filter((v) => v != null && Number.isFinite(Number(v)))
  const equity = blocks
    .filter((b) => b?.mean_roi != null)
    .map((b) => ({ roi: Number(b.mean_roi), at: b.at }))
  if (rois.length < 2) return null
  return { craft_roi: rois, craft_accuracy: accs.length >= 2 ? accs : rois, craft_equity: equity }
}

const SPORT_COLOR = {
  soccer: '#3d8bfd',
  basketball: '#d97706',
  cricket: '#3d9b6c',
}

function StatusPill({ status, n, need }) {
  const building = status === 'building'
  const isNa = status === 'na'
  return (
    <span className={`insight-status ${building ? 'is-building' : isNa ? 'is-na' : 'is-ready'}`}>
      {building ? `building ${fmt(n)}/${fmt(need)}` : isNa ? 'no cache' : `ready · n=${fmt(n)}`}
    </span>
  )
}

/** Multi-series line chart. series = [{key, color, values, dashed?}] */
function MultiLineChart({ title, series, format = (v) => v.toFixed(2), height = 120 }) {
  const norm = (series || []).map((s) => ({
    ...s,
    values: dedupePlateau(asSeriesValues(s.values || [])),
  }))
  const len = Math.max(0, ...norm.map((s) => (s.values || []).length))
  const flat = norm.flatMap((s) => (s.values || []).map(Number).filter(Number.isFinite))
  if (len < 2 || flat.length < 2) {
    return (
      <div className="insight-chart">
        <span className="stat-label">{title}</span>
        <p className="muted">Need ≥2 data blocks.</p>
      </div>
    )
  }
  const w = 520
  const h = height
  const pad = { t: 10, r: 8, b: 18, l: 42 }
  // Clip extreme outliers so one +188% month doesn't squash the rest
  const sorted = [...flat].sort((a, b) => a - b)
  const lo = sorted[Math.floor(sorted.length * 0.05)]
  const hi = sorted[Math.ceil(sorted.length * 0.95) - 1] ?? sorted[sorted.length - 1]
  // Keep zero in view; don't force the whole chart below zero when data is mostly green
  const min = Math.min(0, lo)
  const max = Math.max(0, hi)
  const span = Math.max(max - min, 0.001)
  const xAt = (i) => pad.l + (i / Math.max(len - 1, 1)) * (w - pad.l - pad.r)
  const yAt = (v) => pad.t + (1 - (Math.min(max, Math.max(min, v)) - min) / span) * (h - pad.t - pad.b)
  const zeroY = min < 0 && max > 0 ? yAt(0) : null
  const yTicks = [min, (min + max) / 2, max]
  const xTickIdx = (() => {
    if (len <= 8) return Array.from({ length: len }, (_, i) => i)
    const step = Math.ceil((len - 1) / 5)
    const idxs = [0]
    for (let i = step; i < len - 1; i += step) idxs.push(i)
    idxs.push(len - 1)
    return [...new Set(idxs)]
  })()

  return (
    <div className="insight-chart">
      <span className="stat-label">{title}</span>
      <svg viewBox={`0 0 ${w} ${h}`} className="insight-chart-svg" role="img" aria-label={title}>
        {yTicks.map((t) => (
          <g key={`yt-${t}`}>
            <line
              x1={pad.l}
              x2={w - pad.r}
              y1={yAt(t)}
              y2={yAt(t)}
              stroke="var(--border)"
              strokeWidth="1"
              opacity="0.5"
            />
            <text x={2} y={yAt(t) + 3} fontSize="8" fill="var(--text-muted)">
              {format(t)}
            </text>
          </g>
        ))}
        {zeroY != null && (
          <line x1={pad.l} x2={w - pad.r} y1={zeroY} y2={zeroY} className="craft-chart-zero" />
        )}
        {norm.map((s) => {
          const pts = []
          ;(s.values || []).forEach((v, i) => {
            if (v == null || !Number.isFinite(Number(v))) return
            pts.push(`${xAt(i)},${yAt(Number(v))}`)
          })
          if (pts.length < 2) return null
          return (
            <polyline
              key={s.key}
              points={pts.join(' ')}
              fill="none"
              stroke={s.color}
              strokeWidth={s.dashed ? '1.75' : '2.25'}
              strokeDasharray={s.dashed ? '5 4' : undefined}
              strokeLinejoin="round"
              strokeLinecap="round"
              opacity={s.dashed ? 0.75 : 1}
            />
          )
        })}
        {xTickIdx.map((i) => (
          <text key={`x-${i}`} x={xAt(i)} y={h - 2} fontSize="8" fill="var(--text-muted)" textAnchor="middle">
            {i + 1}
          </text>
        ))}
      </svg>
      <div className="insight-chart-legend">
        {norm.map((s) => {
          const nums = (s.values || []).filter((v) => v != null && Number.isFinite(Number(v)))
          const last = nums.length ? nums[nums.length - 1] : null
          const mean = nums.length ? nums.reduce((a, b) => a + Number(b), 0) / nums.length : null
          return (
            <span key={s.key} className="insight-legend-item">
              <i style={{ background: s.color, opacity: s.dashed ? 0.6 : 1 }} />
              {s.key}
              {mean != null ? ` avg ${format(Number(mean))}` : ''}
              {last != null ? ` last ${format(Number(last))}` : ''}
            </span>
          )
        })}
      </div>
    </div>
  )
}

function AccGauge({ value, label, color }) {
  const v = value == null ? null : Math.max(0, Math.min(1, Number(value)))
  const deg = v == null ? 0 : v * 360
  return (
    <div className="insight-gauge">
      <div
        className="insight-gauge-ring"
        style={{
          background: v == null
            ? 'var(--border)'
            : `conic-gradient(${color} ${deg}deg, var(--border) 0)`,
        }}
      >
        <div className="insight-gauge-hole">
          <strong>{pct(v)}</strong>
        </div>
      </div>
      <span>{label}</span>
    </div>
  )
}

function ReliabilityBars({ buckets }) {
  const rows = (buckets || []).filter((b) => b && (b.n || b.predicted != null))
  if (!rows.length) {
    return <p className="muted">Calibration buckets building - retrain to fill.</p>
  }
  return (
    <div className="insight-calib">
      {rows.map((b, i) => {
        const said = Number(b.predicted)
        const did = Number(b.actual)
        return (
          <div className="insight-calib-row" key={b.range || i}>
            <span className="insight-calib-range">{b.range || `${said}%`}</span>
            <div className="insight-calib-bars">
              <div className="insight-calib-said" style={{ width: `${Math.min(100, said)}%` }} />
              <div className="insight-calib-did" style={{ width: `${Math.min(100, did)}%` }} />
            </div>
            <span className="muted">{said}% → {did}% · n={b.n}</span>
          </div>
        )
      })}
      <small className="muted">Top bar = predicted · bottom = actual hit rate</small>
    </div>
  )
}

function SportGrid({ sports, render }) {
  return (
    <div className="insight-sport-grid">
      {(sports || []).map((cell) => (
        <article key={cell.sport} className={`insight-sport insight-sport--${cell.sport}`}>
          <header>
            <h3>{cell.sport}</h3>
            <StatusPill status={cell.status} n={cell.n} need={cell.need} />
          </header>
          {render(cell)}
        </article>
      ))}
    </div>
  )
}

function InsightContainer({ c, curves, sportKeys }) {
  if (!c) return null
  const craftSportRoi = sportKeys.map((k) => ({
    key: k,
    color: SPORT_COLOR[k],
    values: (curves.craft_sport_roi || {})[k] || [],
  }))
  const craftSportAcc = sportKeys.map((k) => ({
    key: k,
    color: SPORT_COLOR[k],
    values: (curves.craft_sport_accuracy || {})[k] || [],
  }))
  const craftSportVol = sportKeys.map((k) => ({
    key: k,
    color: SPORT_COLOR[k],
    values: (curves.craft_sport_volume || {})[k] || [],
  }))
  const trendRows = curves.betting_trends || []
  const gatedSports = new Set(curves.betting_gated || [])
  // Last 24 months per sport — gated sports still chart (labeled below)
  const bettingRoiBySport = sportKeys
    .map((k) => {
      const rows = trendRows
        .filter((t) => t.sport === k && t.ym && t.roi != null)
        .sort((a, b) => String(a.ym).localeCompare(String(b.ym)))
        .slice(-24)
      return {
        key: gatedSports.has(k) ? `${k} (gated)` : k,
        color: SPORT_COLOR[k],
        values: rows.map((r) => Number(r.roi)),
      }
    })
    .filter((s) => (s.values || []).length >= 2)
  const yearRows = curves.betting_yearly || []
  const bettingYearBySport = sportKeys.map((k) => {
    const rows = yearRows
      .filter((t) => t.sport === k && t.year && t.n != null)
      .sort((a, b) => String(a.year).localeCompare(String(b.year)))
      .slice(-24)
    return {
      key: k,
      color: SPORT_COLOR[k],
      values: rows.map((r) => Number(r.n)),
    }
  })

  return (
    <section className="panel insight-box" data-id={c.id}>
      <div className="insight-box-head">
        <h2 className="panel-title">{c.title}</h2>
        {c.status && <StatusPill status={c.status} n={c.n} need={c.need} />}
      </div>
      {c.desc && <p className="panel-desc">{c.desc}</p>}

      {c.kind === 'sport_grid' && (
        <SportGrid
          sports={c.sports}
          render={(cell) => (
            <dl>
              {cell.corpus != null && <div><dt>Corpus</dt><dd>{fmt(cell.corpus)}</dd></div>}
              {cell.accuracy != null && <div><dt>Accuracy</dt><dd>{pct(cell.accuracy)}</dd></div>}
              {cell.board_n != null && (
                <div><dt>Boards</dt><dd>{cell.board_accuracy != null ? pct(cell.board_accuracy) : '-'} · {fmt(cell.board_n)}</dd></div>
              )}
              {cell.history_accuracy != null && (
                <div><dt>History</dt><dd>{pct(cell.history_accuracy)} · {fmt(cell.history_n)}</dd></div>
              )}
              {cell.primary_accuracy != null && cell.accuracy == null && (
                <div><dt>Primary</dt><dd>{pct(cell.primary_accuracy)}</dd></div>
              )}
              {cell.teams != null && (
                <div><dt>Teams</dt><dd>{fmt(cell.teams)}{cell.intl ? ` · ${fmt(cell.intl)} intl` : ''}</dd></div>
              )}
              {cell.players != null && <div><dt>Players</dt><dd>{fmt(cell.players)}</dd></div>}
              {cell.hit_rate != null && <div><dt>Hit</dt><dd>{pct(cell.hit_rate)}</dd></div>}
              {cell.roi != null && (
                <div><dt>ROI</dt><dd className={cell.gated ? 'delta-down' : ''}>{roiPct(cell.roi)}{cell.gated ? ' gated' : ''}</dd></div>
              )}
              {cell.roi == null && cell.note && String(cell.note).includes('gated') && (
                <div><dt>ROI</dt><dd>gated</dd></div>
              )}
              {cell.avg_edge != null && (
                <div><dt>Avg edge</dt><dd>{`${(Number(cell.avg_edge) * 100).toFixed(1)}pp`}</dd></div>
              )}
              {cell.volume != null && <div><dt>Handle</dt><dd>${fmt(cell.volume)}</dd></div>}
              {cell.users != null && <div><dt>Bettors</dt><dd>{fmt(cell.users)}</dd></div>}
              {cell.fixtures != null && <div><dt>Fixtures</dt><dd>{fmt(cell.fixtures)}</dd></div>}
              {cell.markets != null && <div><dt>Markets</dt><dd>{fmt(cell.markets)}</dd></div>}
              {cell.combos != null && <div><dt>Combos</dt><dd>{fmt(cell.combos)}</dd></div>}
              {cell.priced != null && (
                <div><dt>Priced</dt><dd>{fmt(cell.priced)} / {fmt(cell.events)} · avg books {cell.avg_books != null ? cell.avg_books : '-'}</dd></div>
              )}
              {cell.last_n != null && <div><dt>Last epoch bets</dt><dd>{fmt(cell.last_n)}</dd></div>}
              {cell.span && <div><dt>Span</dt><dd>{cell.span}</dd></div>}
              {cell.note && <div><dt>Note</dt><dd>{cell.note}</dd></div>}
              {c.meta?.note && cell === (c.sports || [])[0] && (
                <div><dt>Cache</dt><dd>{c.meta.note}</dd></div>
              )}
              {cell.n != null && cell.corpus == null && cell.accuracy == null && cell.hit_rate == null && cell.roi == null && cell.teams == null && cell.players == null && cell.volume == null && cell.priced == null && cell.last_n == null && !cell.note && (
                <div><dt>Sample</dt><dd>{fmt(cell.n)}</dd></div>
              )}
            </dl>
          )}
        />
      )}

      {c.kind === 'targets' && (
        <div className="stat-grid stat-grid--compact">
          <div className="stat-cell">
            <span className="stat-label">Target overall ROI</span>
            <strong className="stat-value">{roiPct(c.target_roi)}</strong>
            <small>all sports {'>'} 0</small>
          </div>
          <div className="stat-cell">
            <span className="stat-label">Target accuracy</span>
            <strong className="stat-value">{pct(c.target_accuracy)}</strong>
          </div>
          <div className="stat-cell">
            <span className="stat-label">Holdout ROI</span>
            <strong className={`stat-value ${Number(c.holdout_roi ?? c.best_roi) >= 0 ? 'delta-up' : ''}`}>
              {c.holdout_roi == null && c.best_roi == null ? '—' : roiPct(c.holdout_roi ?? c.best_roi)}
            </strong>
            <small>{c.holdout_roi == null ? 'empty epoch · champion below' : 'same frozen matches every run'}</small>
          </div>
          <div className="stat-cell">
            <span className="stat-label">Holdout hit rate</span>
            <strong className="stat-value">{pct(c.holdout_accuracy ?? c.best_accuracy)}</strong>
            <small>{fmt(c.best_bets)} bets at best · {fmt(c.n_epochs)} epochs</small>
          </div>
          <div className="stat-cell">
            <span className="stat-label">Gate</span>
            <strong className="stat-value">{trainGateLabel(c)}</strong>
            <small>25% overall · each sport {'>'} 0 · monthly green</small>
          </div>
          {c.gates?.sports && Object.entries(c.gates.sports).map(([sp, g]) => (
            <div className="stat-cell" key={sp}>
              <span className="stat-label">{sp} sport gate</span>
              <strong className={`stat-value ${g.ok ? 'delta-up' : ''}`}>{g.ok ? 'OK' : 'OPEN'}</strong>
              <small>n={fmt(g.n)} · {g.roi != null && Number(g.roi) >= 0 ? roiPct(g.roi) : 'gated'}</small>
            </div>
          ))}
          {c.gates?.monthly?.sports && Object.entries(c.gates.monthly.sports).map(([sp, g]) => (
            <div className="stat-cell" key={`m-${sp}`}>
              <span className="stat-label">{sp} monthly</span>
              <strong className={`stat-value ${g.ok ? 'delta-up' : (g.mean_roi != null && Number(g.mean_roi) < 0 ? 'delta-down' : '')}`}>
                {g.ok ? 'OK' : (g.mean_roi != null && Number(g.mean_roi) < 0 ? 'RED' : 'OPEN')}
              </strong>
              <small>
                {g.mean_roi != null
                  ? roiPct(g.mean_roi)
                  : (g.reason === 'thin_epochs' || g.reason === 'thin_months' ? 'building series' : (g.reason || '…'))}
              </small>
            </div>
          ))}
        </div>
      )}

      {c.kind === 'market_list' && (
        <div className="stat-grid stat-grid--compact">
          {(c.rows || []).map((row) => (
            <div className="stat-cell" key={row.market}>
              <span className="stat-label">{String(row.market || '').replace(/_/g, ' ')}</span>
              <strong className="stat-value">{pct(row.accuracy ?? row.hit_rate)}</strong>
              <small>
                <StatusPill status={row.status} n={row.n} need={row.need} />
              </small>
            </div>
          ))}
        </div>
      )}

      {c.kind === 'tier_list' && (
        <div className="stat-grid stat-grid--compact">
          {(c.rows || []).map((row) => (
            <div className="stat-cell" key={row.tier}>
              <span className="stat-label">≥{row.tier}% · {row.label}</span>
              <strong className="stat-value">{pct(row.accuracy)}</strong>
              <small><StatusPill status={row.status} n={row.n} need={row.need} /></small>
            </div>
          ))}
        </div>
      )}

      {c.kind === 'calibration' && (
        <>
          <div className="stat-grid stat-grid--compact">
            <div className="stat-cell">
              <span className="stat-label">Brier (lower better)</span>
              <strong className="stat-value">{c.brier != null ? Number(c.brier).toFixed(3) : 'building'}</strong>
            </div>
            <div className="stat-cell">
              <span className="stat-label">Market replay</span>
              <strong className="stat-value">{pct(c.market_replay_accuracy)}</strong>
            </div>
            <div className="stat-cell">
              <span className="stat-label">Slip leg accuracy</span>
              <strong className="stat-value">{pct(c.leg_accuracy)}</strong>
            </div>
          </div>
          <ReliabilityBars buckets={c.reliability} />
        </>
      )}

      {c.kind === 'factors' && (
        <>
          <div className="insight-factor-sport">
            {sportKeys.map((k) => (
              <div key={k} className="stat-cell">
                <span className="stat-label">{k}</span>
                <strong className="stat-value">{fmt((c.by_sport || {})[k] || 0)}</strong>
              </div>
            ))}
            <div className="stat-cell">
              <span className="stat-label">nodes</span>
              <strong className="stat-value">{fmt(c.total_nodes)}</strong>
              <small>{fmt(c.total_edges)} edges</small>
            </div>
          </div>
          <div className="insight-factor-kinds">
            {Object.entries(c.by_type || {}).map(([kind, n]) => (
              <span key={kind} className="insight-factor-chip">{kind} · {fmt(n)}</span>
            ))}
          </div>
          <ul className="insight-factor-list">
            {(c.catalog || []).map((f) => (
              <li key={f.id}><strong>{f.label}</strong><span className="muted">{f.sports}</span></li>
            ))}
          </ul>
        </>
      )}

      {c.kind === 'league_list' && (
        <div className="stat-grid stat-grid--compact">
          {(c.rows || []).map((row) => (
            <div className="stat-cell" key={row.code || row.league}>
              <span className="stat-label">{row.league}</span>
              <strong className="stat-value">{fmt(row.n)}</strong>
              <small><StatusPill status={row.status} n={row.n} need={row.need} /></small>
            </div>
          ))}
          {!(c.rows || []).length && <p className="muted">League CSVs not cached yet - Retrain pulls football-data.</p>}
        </div>
      )}

      {c.kind === 'health' && (
        <div className="stat-grid stat-grid--compact">
          {(c.rows || []).map((row) => (
            <div className="stat-cell" key={row.id}>
              <span className="stat-label">{row.label}</span>
              <strong className="stat-value">{row.status === 'ready' ? 'ready' : 'building'}</strong>
              <small>{fmt(row.n)} / need {fmt(row.need)}</small>
            </div>
          ))}
        </div>
      )}

      {c.kind === 'bullets' && (
        <ul className="insight-bullets">
          {(c.rows || []).map((line) => <li key={line}>{line}</li>)}
        </ul>
      )}

      {c.kind === 'chart' && c.chart === 'craft_equity' && (
        <MultiLineChart
          title="Block paper ROI (not live bankroll)"
          series={[{
            key: 'block_roi',
            color: SPORT_COLOR.cricket,
            values: curves.craft_equity || [],
          }]}
          format={(v) => chartRoi(v)}
        />
      )}
      {c.kind === 'chart' && c.chart === 'betting_yearly_volume' && (
        <div className="insight-charts">
          {bettingYearBySport.map((s) => (
            <MultiLineChart key={s.key} title={`${s.key} bets/year`} series={[s]} format={(v) => fmt(v)} height={110} />
          ))}
        </div>
      )}
      {c.kind === 'chart' && c.chart === 'betting_monthly_roi' && (
        <div className="insight-charts">
          <p className="muted">
            Close-price monthly pairs (history). Separate from holdout craft ROI in box 7.
            {gatedSports.size > 0 ? ` Live-pick gate still on: ${[...gatedSports].join(', ')}.` : ''}
          </p>
          {bettingRoiBySport.map((s) => (
            <MultiLineChart key={s.key} title={`${s.key} monthly ROI`} series={[s]} format={(v) => chartRoi(v)} height={110} />
          ))}
          {!bettingRoiBySport.length && (
            <p className="muted">No monthly series yet — wait for betting evolution data on this host.</p>
          )}
        </div>
      )}
      {c.kind === 'chart' && c.chart === 'craft_overall' && (
        <div className="insight-charts">
          <MultiLineChart
            title="Block desk ROI"
            series={[
              { key: 'all 3', color: 'var(--accent, #c4a574)', values: curves.craft_roi || [] },
              { key: 'soccer', color: SPORT_COLOR.soccer, values: (curves.craft_sport_roi || {}).soccer || [] },
              { key: 'basketball', color: SPORT_COLOR.basketball, values: (curves.craft_sport_roi || {}).basketball || [] },
              { key: 'cricket', color: SPORT_COLOR.cricket, values: (curves.craft_sport_roi || {}).cricket || [] },
            ]}
            format={(v) => chartRoi(v)}
          />
          <MultiLineChart
            title="Craft hit rate by block"
            series={[
              { key: 'blocks', color: 'var(--green, #3d8b6e)', values: curves.craft_accuracy || [] },
            ]}
            format={(v) => pct(v)}
          />
        </div>
      )}
      {c.chart === 'craft_sport_roi' && (
        <MultiLineChart title="Sport ROI per block" series={craftSportRoi} format={(v) => chartRoi(v)} />
      )}
      {c.chart === 'craft_sport_accuracy' && (
        <MultiLineChart title="Sport hit rate per block" series={craftSportAcc} format={(v) => pct(v)} />
      )}
      {c.chart === 'craft_sport_volume' && (
        <MultiLineChart title="Tickets per block" series={craftSportVol} format={(v) => fmt(v)} />
      )}
    </section>
  )
}

export default function ModelPage() {
  const cached = peekModelInsights()
  const [ins, setIns] = useState(cached)
  const [loading, setLoading] = useState(!cached)
  const [deskLoading, setDeskLoading] = useState(!cached)
  const [retraining, setRetraining] = useState(false)
  const [paperBusy, setPaperBusy] = useState(false)
  const [err, setErr] = useState(null)
  // Unlock entry as soon as craft snapshot paints — don't wait on full insights
  useEntryReady(!loading)

  const craftFromSnap = (craft) => {
    const fromBlocks = blocksToCurves(craft?.blocks)
    return {
      status: 'loading',
      total_corpus: 0,
      sports: {},
      containers: [],
      curves: {
        craft_roi: fromBlocks?.craft_roi || craft?.roi_trend || [],
        craft_accuracy: fromBlocks?.craft_accuracy || craft?.accuracy_trend || [],
        craft_equity: fromBlocks?.craft_equity || craft?.equity_curve || [],
        craft_sport_roi: {},
        craft_sport_accuracy: {},
        craft_sport_volume: {},
      },
      craft: {
        n_epochs: craft?.n_epochs || 0,
        hit_target: craft?.hit_target,
        best_roi: (craft?.best?.roi != null && Number(craft.best.roi) > -0.5)
          ? craft.best.roi
          : craft?.train_status?.holdout_roi,
        best_accuracy: craft?.best?.accuracy ?? craft?.train_status?.holdout_accuracy,
        best_bets: craft?.best?.bets,
        target_roi: 0.25,
        target_accuracy: 0.60,
        holdout_roi: craft?.train_status?.holdout_roi,
        holdout_accuracy: craft?.train_status?.holdout_accuracy,
        train_status: craft?.train_status,
        block: craft?.block,
        block_prev: craft?.block_prev,
        blocks: craft?.blocks,
      },
      insights: [],
    }
  }

  const load = (retrain = false) => {
    if (retrain) setRetraining(true)
    else if (!ins) {
      setLoading(true)
      setDeskLoading(true)
    } else {
      // Soft refresh — keep painted desk, only banner spinner
      setDeskLoading(true)
    }
    setErr(null)

    // Fast path: craft snapshot (~ms) so the page isn't a blank hang
    if (!retrain && !ins) {
      fetchCraftProgress()
        .then((craft) => {
          setIns((prev) => prev?.containers?.length ? prev : craftFromSnap(craft))
          setLoading(false)
        })
        .catch(() => {})
    }

    const job = retrain
      ? fetchModelReport({ retrain: true }).then(() => fetchModelInsights({ force: true }))
      : fetchModelInsights({ force: retrain }).catch(async (e) => {
          const [rep, craft] = await Promise.all([
            fetchModelReport({ retrain: false }).catch(() => null),
            fetchCraftProgress().catch(() => null),
          ])
          if (rep?.insights) return rep.insights
          if (!rep && !craft) throw e
          return craftFromSnap(craft)
        })

    job
      .then((d) => { setIns(d); setErr(null) })
      .catch((e) => { setErr(String(e)) })
      .finally(() => {
        setLoading(false)
        setDeskLoading(false)
        setRetraining(false)
      })
  }

  const runPaper = () => {
    setPaperBusy(true)
    runPaperCycle({
      untilRoi: true,
      targetRoi: 0.25,
      targetAcc: 0.60,
      maxEpochs: 0, // unlimited - only stops on real ROI+acc gate
      bankroll: 10000,
      matchBudget: 200,
    })
      .then(() => fetchModelInsights())
      .then(setIns)
      .catch(() => {})
      .finally(() => setPaperBusy(false))
  }

  // Craft status only - do NOT re-fetch full insights every few seconds
  // (that made charts look "live" / zigzaggy; user wants block comparisons).
  useEffect(() => {
    const state = ins?.craft?.train_status?.state
    if (state !== 'running') return undefined
    const id = setInterval(() => {
      fetchCraftProgress()
        .then((craft) => {
          setIns((prev) => {
            if (!prev) return prev
            const ts = craft?.train_status || {}
            // ponytail: don't rewrite curves from poll — archive blocks duplicate plateaus
            return {
              ...prev,
              craft: {
                ...prev.craft,
                train_status: ts,
                n_epochs: craft?.n_epochs ?? prev.craft?.n_epochs,
                best_roi: (craft?.best?.roi != null && Number(craft.best.roi) > -0.5)
                  ? craft.best.roi
                  : (ts.champion_roi ?? ts.holdout_roi ?? prev.craft?.best_roi),
                best_accuracy: craft?.best?.accuracy ?? ts.champion_accuracy ?? ts.holdout_accuracy ?? prev.craft?.best_accuracy,
                holdout_roi: ts.holdout_roi ?? ts.champion_roi ?? prev.craft?.holdout_roi,
                holdout_accuracy: ts.holdout_accuracy ?? ts.champion_accuracy ?? prev.craft?.holdout_accuracy,
                best_bets: craft?.best?.bets ?? prev.craft?.best_bets,
                hit_target: craft?.hit_target ?? prev.craft?.hit_target,
                block: craft?.block,
                block_prev: craft?.block_prev,
                blocks: craft?.blocks,
              },
            }
          })
        })
        .catch(() => {})
    }, 20000)
    return () => clearInterval(id)
  }, [ins?.craft?.train_status?.state])

  useEffect(() => { load(false) }, [])

  if (loading && !ins) {
    return (
      <div className="page model-page">
        <div className="model-boot" role="status" aria-live="polite">
          <div className="spinner" />
          <p>Loading model desk…</p>
          <small className="muted">Craft snapshot first, then full charts.</small>
        </div>
      </div>
    )
  }
  if (err && !ins) return <div className="page"><p className="muted">Could not load: {err}</p></div>

  const sportKeys = ['soccer', 'basketball', 'cricket']
  const curves = ins?.curves || {}
  const containers = ins?.containers || []
  const craft = ins?.craft || {}

  return (
    <div className="page model-page insight-page">
      {deskLoading && (
        <div className="model-desk-banner" role="status">
          <div className="spinner small" />
          <span>Refreshing desk charts…</span>
        </div>
      )}
      <header className="page-header">
        <div>
          <h1>Model</h1>
          <p className="subtitle">
            {overviewLine(ins, craft)}
          </p>
        </div>
        <div className="insight-header-actions">
          <button type="button" className="btn-secondary" onClick={runPaper} disabled={paperBusy || retraining}>
            {paperBusy ? 'Training until targets…' : 'Train until ROI+acc'}
          </button>
          <button type="button" className="btn-secondary" onClick={() => load(true)} disabled={retraining}>
            <IconRefresh width={16} height={16} />
            {retraining ? 'Retraining…' : 'Retrain'}
          </button>
        </div>
      </header>

      <section className="panel insight-hero">
        <div className="insight-hero-stats">
          <div className="stat-cell">
            <span className="stat-label">Corpus</span>
            <strong className="stat-value">{fmt(ins?.total_corpus)}</strong>
            <small>3 sports · esports excluded</small>
          </div>
          <div className="stat-cell">
            <span className="stat-label">Insight boxes</span>
            <strong className="stat-value">{fmt(containers.length)}</strong>
            <small>3 sports live</small>
          </div>
          <div className="stat-cell">
            <span className="stat-label">Champion ROI</span>
            <strong className={`stat-value ${Number(deskRoi(craft)) >= 0 ? 'delta-up' : ''}`}>
              {roiPct(deskRoi(craft))}
            </strong>
            <small>best saved desk · target {roiPct(craft.target_roi || 0.25)}</small>
          </div>
          <div className="stat-cell">
            <span className="stat-label">Latest holdout ROI</span>
            <strong className={`stat-value ${liveHoldoutRoi(craft) == null ? '' : (liveHoldoutRoi(craft) >= 0 ? 'delta-up' : 'delta-down')}`}>
              {liveHoldoutRoi(craft) == null ? '—' : roiPct(liveHoldoutRoi(craft))}
            </strong>
            <small>
              {liveHoldoutRoi(craft) == null
                ? 'this epoch has no graded bets yet · see champion'
                : 'current graded run · can lag champion'}
            </small>
          </div>
          <div className="stat-cell">
            <span className="stat-label">Live hit rate</span>
            <strong className="stat-value">{pct(deskHitRate(craft))}</strong>
            <small>target {pct(craft.target_accuracy || 0.60)}</small>
          </div>
          <div className="stat-cell">
            <span className="stat-label">Train gate</span>
            <strong className="stat-value">{trainGateLabel(craft)}</strong>
            <small>{fmt(craft.train_status?.epoch || craft.n_epochs)} epochs</small>
          </div>
          <div className="stat-cell">
            <span className="stat-label">Factors</span>
            <strong className="stat-value">{fmt(ins?.factors?.total_nodes || containers.find((c) => c.id === '18_factor_graph')?.total_nodes)}</strong>
            <small>trained graph nodes</small>
          </div>
        </div>
      </section>

      {containers.length === 0 && (
        <section className="panel">
          <p className="muted" role="alert">
            {deskLoading
              ? 'Loading insight boxes…'
              : (ins?.insights?.[0] || 'Insight boxes unavailable. Open Model again in a minute, or hit Retrain after craft files finish syncing.')}
          </p>
        </section>
      )}

      {containers.map((c) => (
        <InsightContainer key={c.id} c={c} curves={curves} sportKeys={sportKeys} />
      ))}
    </div>
  )
}
