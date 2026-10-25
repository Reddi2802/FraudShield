'use client'
import { useEffect, useState } from 'react'
import { ChevronRight, FileSearch, RefreshCw } from 'lucide-react'
import { api } from '@/lib/api'
import type { CaseDetail, CaseSummary, Decision } from '@/lib/types'
import { date } from '@/lib/format'
import { Badge } from '@/components/Badge'
import { CaseDrawer } from '@/components/CaseDrawer'
import { Header } from '@/components/Header'

export function InvestigatorPage() {
  const [status, setStatus] = useState('open')
  const [cases, setCases] = useState<CaseSummary[]>([])
  const [selected, setSelected] = useState<CaseDetail | null>(null)
  const [error, setError] = useState('')
  const load = () =>
    api
      .cases(status)
      .then(setCases)
      .catch((e) => setError(e.message))
  useEffect(() => {
    load()
  }, [status])
  return (
    <>
      <Header
        title="Case queue"
        action={
          <span className="secure-pill">
            <FileSearch /> Human review
          </span>
        }
      />
      <div className="content">
        <div className="queue-tabs">
          {['open', 'in_review', 'resolved'].map((s) => (
            <button className={status === s ? 'active' : ''} onClick={() => setStatus(s)} key={s}>
              {s === 'open' ? 'Open' : s === 'in_review' ? 'In review' : 'Resolved'}
              <span>{status === s ? cases.length : ''}</span>
            </button>
          ))}
        </div>
        <section className="panel queue-panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Priority sorted</p>
              <h2>
                {status === 'open'
                  ? 'Open cases'
                  : status === 'in_review'
                    ? 'Cases in review'
                    : 'Resolved cases'}
              </h2>
            </div>
            <button className="icon-button" onClick={load} aria-label="Refresh queue">
              <RefreshCw />
            </button>
          </div>
          {error ? (
            <div className="error-box">{error}</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Case</th>
                    <th>Decision</th>
                    <th>Risk score</th>
                    <th>Opened</th>
                    <th>Transaction</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {cases
                    .filter((c) => c.status === status)
                    .map((c) => (
                      <tr
                        className="clickable"
                        onClick={() =>
                          api
                            .caseDetail(c.case_id)
                            .then(setSelected)
                            .catch((e) => setError(e.message))
                        }
                        key={c.case_id}
                      >
                        <td>
                          <strong>#{c.case_id}</strong>
                        </td>
                        <td>
                          <Badge decision={c.decision} />
                        </td>
                        <td>
                          <div className="risk-cell">
                            <div className="mini-bar">
                              <span style={{ width: `${(c.risk_score || 0) * 100}%` }} />
                            </div>
                            <b>{c.risk_score?.toFixed(2)}</b>
                          </div>
                        </td>
                        <td>{date(c.opened_at)}</td>
                        <td>#{c.transaction_id}</td>
                        <td>
                          <ChevronRight />
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
              {!cases.filter((c) => c.status === status).length && (
                <div className="empty-table">No cases in this queue.</div>
              )}
            </div>
          )}
        </section>
      </div>
      {selected && (
        <CaseDrawer
          detail={selected}
          close={() => setSelected(null)}
          refresh={() => {
            setSelected(null)
            load()
          }}
        />
      )}
    </>
  )
}
