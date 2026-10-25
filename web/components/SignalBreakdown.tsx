'use client'
import type { Signal } from '@/lib/types'

export function SignalBreakdown({ signals }: { signals?: Signal[] | null }) {
  if (!signals?.length) return null
  const names: Record<Signal['agent'], string> = { rules: 'Rules', device: 'Device trust', behavioral: 'Behavioral model', network: 'Network' }
  return (
    <section className="signal-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Decision inputs</p>
          <h3>Signal breakdown</h3>
        </div>
        <span className="muted-text">Weighted noisy-OR</span>
      </div>
      <div className="signal-grid">
        {['rules', 'device', 'behavioral', 'network'].map((a) => {
          const s = signals.find((x) => x.agent === a)
          if (!s) return null
          return (
            <div className={`signal-card ${s.score == null ? 'abstained' : ''}`} key={a}>
              <div className="signal-top">
                <strong>{names[s.agent]}</strong>
                {s.score == null ? (
                  <span className="badge muted">Abstained</span>
                ) : (
                  <b>{s.score.toFixed(2)}</b>
                )}
              </div>
              {s.score != null && (
                <div className="mini-bar">
                  <span style={{ width: `${s.score * 100}%` }} />
                </div>
              )}
              <p>{s.reason}</p>
              <small>Fusion weight {s.weight.toFixed(1)}</small>
            </div>
          )
        })}
      </div>
      <p className="footnote">Signals are fused with a weighted noisy-OR; abstaining agents are skipped.</p>
    </section>
  )
}
