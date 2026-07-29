/** Loading buffer - pulse blocks while boards scrape. Never retriggers intro. */
export default function BoardBuffer({ rows = 4, label = 'Loading boards…' }) {
  return (
    <div className="board-buffer" role="status" aria-live="polite" aria-busy="true">
      <div className="board-buffer-bar">
        <span className="board-buffer-pulse" />
        <span>{label}</span>
      </div>
      <div className="board-buffer-grid">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="board-buffer-card" style={{ animationDelay: `${i * 0.08}s` }} />
        ))}
      </div>
    </div>
  )
}
