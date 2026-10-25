'use client'
import { ShieldCheck } from 'lucide-react'

export function Kpi({ label, value, icon: Icon }: { label: string; value: string; icon: typeof ShieldCheck }) {
  return (
    <div className="kpi">
      <div className="kpi-icon">
        <Icon />
      </div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
    </div>
  )
}

export function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="panel chart-card">
      <p className="eyebrow">Distribution</p>
      <h2>{title}</h2>
      {children}
    </section>
  )
}

export function BarChart({ data }: { data: [string, number, string][] }) {
  const max = Math.max(...data.map((d) => d[1]))
  return (
    <div className="bar-chart">
      {data.map(([label, value, color]) => (
        <div className="bar-item" key={label}>
          <div className="bar-meta">
            <span>{label}</span>
            <strong>{value.toLocaleString()}</strong>
          </div>
          <div className="bar-track">
            <span style={{ width: `${max ? (value / max) * 100 : 0}%`, backgroundColor: color }} />
          </div>
        </div>
      ))}
    </div>
  )
}
