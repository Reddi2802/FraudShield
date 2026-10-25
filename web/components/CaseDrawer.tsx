'use client'
import { useState } from 'react'
import { Check, CheckCircle2, XCircle } from 'lucide-react'
import { api, ApiError } from '@/lib/api'
import type { CaseDetail, Customer } from '@/lib/types'
import { money, date } from '@/lib/format'
import { Badge } from '@/components/Badge'
import { Explanation } from '@/components/Explanation'
import { RiskGauge } from '@/components/RiskGauge'
import { SignalBreakdown } from '@/components/SignalBreakdown'

export function CaseDrawer({
  detail,
  close,
  refresh,
}: {
  detail: CaseDetail
  close: () => void
  refresh: () => void
}) {
  const [label, setLabel] = useState<'fraud' | 'not_fraud'>('fraud')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      await api.feedback(detail.case_id, { label, notes: notes.trim() || undefined })
      refresh()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError('This case was already resolved by someone else.')
        setTimeout(refresh, 1500)
      } else {
        setError(e instanceof Error ? e.message : 'Unable to resolve case')
      }
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="drawer-backdrop" onClick={close}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <p className="eyebrow">Case detail</p>
            <h2>#{detail.case_id}</h2>
          </div>
          <button className="icon-button" onClick={close} aria-label="Close">
            <XCircle />
          </button>
        </div>
        <div className="drawer-body">
          <div className="detail-amount">
            <span>Transaction amount</span>
            <strong>{money(detail.transaction.amount, detail.transaction.currency)}</strong>
            <Badge decision={detail.decision} />
          </div>
          <div className="detail-grid">
            <div>
              <span>Customer ID</span>
              <strong>#{detail.transaction.customer_id}</strong>
            </div>
            <div>
              <span>Transaction</span>
              <strong>#{detail.transaction_id}</strong>
            </div>
            <div>
              <span>Opened</span>
              <strong>{date(detail.opened_at)}</strong>
            </div>
          </div>
          <div className="panel inset">
            <div className="section-heading">
              <h3>Risk assessment</h3>
              <span className="tabular">{detail.risk_score?.toFixed(2)}</span>
            </div>
            <RiskGauge score={detail.risk_score} />
            <Explanation text={detail.explanation} />
          </div>
          <SignalBreakdown signals={detail.signals} />
          {detail.feedback ? (
            <div className="resolved-card">
              <CheckCircle2 />
              <div>
                <strong>Resolved as {detail.feedback.label === 'fraud' ? 'fraud' : 'not fraud'}</strong>
                <p>{detail.feedback.notes || 'No notes added.'}</p>
                <small>
                  Investigator #{detail.feedback.investigator_id} · {date(detail.feedback.submitted_at)}
                </small>
              </div>
            </div>
          ) : (
            <form className="feedback-form" onSubmit={submit}>
              <div className="section-heading">
                <div>
                  <p className="eyebrow">Investigator verdict</p>
                  <h3>Resolve this case</h3>
                </div>
              </div>
              <div className="radio-row">
                <label className={label === 'fraud' ? 'selected' : ''}>
                  <input type="radio" checked={label === 'fraud'} onChange={() => setLabel('fraud')} />
                  Fraud
                </label>
                <label className={label === 'not_fraud' ? 'selected' : ''}>
                  <input
                    type="radio"
                    checked={label === 'not_fraud'}
                    onChange={() => setLabel('not_fraud')}
                  />
                  Not fraud
                </label>
              </div>
              <label>
                Notes{' '}
                <textarea
                  maxLength={500}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Add context for the next reviewer…"
                />
                <small>{notes.length} / 500</small>
              </label>
              {error && <div className="error-box">{error}</div>}
              <button className="primary-button" disabled={busy}>
                {busy ? 'Submitting…' : 'Submit verdict'}
                <Check />
              </button>
            </form>
          )}
        </div>
      </aside>
    </div>
  )
}
