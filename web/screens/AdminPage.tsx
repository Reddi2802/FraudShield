'use client'
import { useEffect, useState } from 'react'
import { CircleDollarSign, Flag, ShieldCheck, UserRound } from 'lucide-react'
import { api } from '@/lib/api'
import type { Overview } from '@/lib/types'
import { date } from '@/lib/format'
import { BarChart } from '@/components/AdminWidgets'
import { ChartCard } from '@/components/AdminWidgets'
import { Header } from '@/components/Header'
import { Kpi } from '@/components/AdminWidgets'

const num = (v: number | null | undefined, digits: number, suffix = '') =>
  v == null ? '—' : `${v.toFixed(digits)}${suffix}`
const pct = (v: number | null | undefined) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)

export function AdminPage() {
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    api
      .overview()
      .then(setData)
      .catch((e: Error) => setError(e.message))
  }, [])
  if (error)
    return (
      <>
        <Header title="Admin overview" />
        <div className="content">
          <div className="error-box">{error}</div>
        </div>
      </>
    )
  if (!data)
    return (
      <>
        <Header title="Admin overview" />
        <div className="content">
          <div className="loading-block">Loading overview…</div>
        </div>
      </>
    )
  const labelTotal = (data.feedback.fraud || 0) + (data.feedback.not_fraud || 0)
  const fraudShare = labelTotal ? ((data.feedback.fraud || 0) / labelTotal) * 100 : 0
  const bars: [string, number, string][] = [
    ['Allow', data.decisions.allow || 0, '#198754'],
    ['Flag', data.decisions.flag || 0, '#c88719'],
    ['Block', data.decisions.block || 0, '#c94b4b'],
  ]
  const caseBars: [string, number, string][] = [
    ['Open', data.cases.open || 0, '#c88719'],
    ['In review', data.cases.in_review || 0, '#7c6be8'],
    ['Resolved', data.cases.resolved || 0, '#198754'],
  ]
  return (
    <>
      <Header title="Admin overview" action={<span className="demo-pill">Read-only demo</span>} />
      <div className="content">
        <div className="kpi-grid">
          <Kpi label="Customers" value={data.customers.toLocaleString()} icon={UserRound} />
          <Kpi label="Transactions" value={data.transactions.toLocaleString()} icon={CircleDollarSign} />
          <Kpi label="Scored by pipeline" value={data.assessments.toLocaleString()} icon={ShieldCheck} />
        </div>
        <div className="charts-grid">
          <ChartCard title="Decisions">
            <BarChart data={bars} />
          </ChartCard>
          <ChartCard title="Cases by status">
            <BarChart data={caseBars} />
          </ChartCard>
        </div>
        <div className="admin-grid">
          <section className="panel verdict-card">
            <p className="eyebrow">Investigator verdicts</p>
            <h2>Human feedback split</h2>
            <div
              className="verdict-donut"
              style={
                {
                  '--fraud': `${fraudShare}%`,
                } as React.CSSProperties
              }
            >
              <div>
                <strong>{(data.feedback.fraud || 0) + (data.feedback.not_fraud || 0)}</strong>
                <span>labels</span>
              </div>
            </div>
            <div className="legend">
              <span>
                <i className="dot fraud" />
                Fraud <b>{data.feedback.fraud || 0}</b>
              </span>
              <span>
                <i className="dot not-fraud" />
                Not fraud <b>{data.feedback.not_fraud || 0}</b>
              </span>
            </div>
          </section>
          <section className="panel model-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Model health</p>
                <h2>Behavioral model</h2>
              </div>
              {data.model && <span className="status-dot">● Registered</span>}
            </div>
            {data.model ? (
              <>
                <div className="model-type">
                  <strong>{data.model.type}</strong>
                  <span>Trained {date(data.model.trained_at)}</span>
                </div>
                <div className="metric-grid">
                  {[
                    ['PR-AUC lift', num(data.model.metrics.pr_auc_lift, 1, 'x')],
                    ['ROC-AUC', num(data.model.metrics.roc_auc, 3)],
                    ['Flag precision', pct(data.model.metrics.flag_precision)],
                    ['Flag recall', pct(data.model.metrics.flag_recall)],
                  ].map(([l, v]) => (
                    <div key={l}>
                      <span>{l}</span>
                      <strong>{v}</strong>
                    </div>
                  ))}
                </div>
                <div className="retrain">
                  <div className="section-heading">
                    <strong>Retraining readiness</strong>
                    <span>
                      {data.retraining.labels_since_model} / {data.retraining.threshold} labels
                    </span>
                  </div>
                  <div className="progress">
                    <span
                      style={{
                        width: `${Math.min(100, (data.retraining.labels_since_model / data.retraining.threshold) * 100)}%`,
                      }}
                    />
                  </div>
                  <small>
                    {data.retraining.reached
                      ? 'Threshold reached. Labels are counted but not yet used for training (ADR-025).'
                      : `${data.retraining.threshold - data.retraining.labels_since_model} more labels until the threshold. Labels are counted but not yet used for training (ADR-025).`}
                  </small>
                </div>
              </>
            ) : (
              <div className="empty-result">
                <h3>No model registered</h3>
                <p>Model metrics will appear after the first training run.</p>
              </div>
            )}
          </section>
        </div>
      </div>
    </>
  )
}
