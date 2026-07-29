/** Cumulative P/L line chart for the portfolio page. */
export default function PortfolioCurve({ points = [], formatMoney }) {
  if (!points.length) return null

  const w = 640
  const h = 220
  const pad = { top: 16, right: 12, bottom: 28, left: 48 }
  const innerW = w - pad.left - pad.right
  const innerH = h - pad.top - pad.bottom

  const values = points.map((p) => Number(p.running_profit_value) || 0)
  const endVal = values[values.length - 1] || 0
  const positive = endVal >= 0
  const minV = Math.min(0, ...values)
  const maxV = Math.max(0, ...values)
  const span = Math.max(maxV - minV, 1)

  const x = (i) => pad.left + (i / Math.max(1, points.length - 1)) * innerW
  const y = (v) => pad.top + innerH - ((v - minV) / span) * innerH

  const linePts = points.map((p, i) => `${x(i)},${y(p.running_profit_value || 0)}`).join(' ')
  const zeroY = y(0)
  const areaPts = `${x(0)},${zeroY} ${linePts} ${x(points.length - 1)},${zeroY}`

  const yTicks = [minV, minV + span * 0.5, maxV].filter((v, i, arr) => i === 0 || Math.abs(v - arr[i - 1]) > span * 0.08)

  return (
    <div className="portfolio-curve-wrap">
      <svg className="portfolio-curve-svg" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Cumulative profit chart">
        {yTicks.map((tick) => (
          <g key={tick}>
            <line
              x1={pad.left}
              x2={w - pad.right}
              y1={y(tick)}
              y2={y(tick)}
              className="portfolio-curve-grid"
            />
            <text x={pad.left - 8} y={y(tick) + 4} className="portfolio-curve-axis" textAnchor="end">
              {formatMoney(tick)}
            </text>
          </g>
        ))}
        <line x1={pad.left} x2={w - pad.right} y1={zeroY} y2={zeroY} className="portfolio-curve-zero" />
        <polygon points={areaPts} className={`portfolio-curve-area ${positive ? 'up' : 'down'}`} />
        <polyline points={linePts} className={`portfolio-curve-line ${positive ? 'up' : 'down'}`} fill="none" />
        {points.map((p, i) => (
          <circle
            key={`${p.i}-${i}`}
            cx={x(i)}
            cy={y(p.running_profit_value || 0)}
            r={4}
            className={`portfolio-curve-dot ${(p.running_profit_value || 0) >= 0 ? 'up' : 'down'}`}
          >
            <title>{`${p.label}: ${formatMoney(p.running_profit_value)}`}</title>
          </circle>
        ))}
      </svg>
      <div className="portfolio-curve-legend">
        <span>Oldest</span>
        <span>Running bankroll after each settled bet</span>
        <span>Newest</span>
      </div>
    </div>
  )
}
