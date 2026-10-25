'use client'

export function RiskGauge({ score }: { score: number | null }) {
  const value = score ?? 0
  return (
    <div className="gauge-wrap">
      <div className="gauge">
        <span className="gauge-fill" style={{ width: `${value * 100}%` }} />
        <i className="threshold t1" />
        <i className="threshold t2" />
      </div>
      <div className="gauge-labels">
        <span>0.00</span>
        <span className="score">{score == null ? '—' : score.toFixed(2)}</span>
        <span>1.00</span>
      </div>
    </div>
  )
}
