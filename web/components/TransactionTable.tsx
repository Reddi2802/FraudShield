'use client'
import type { MyTransaction } from '@/lib/types'
import { money, date } from '@/lib/format'
import { StatusBadge } from '@/components/StatusBadge'

export function TransactionTable({ transactions }: { transactions: MyTransaction[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Transaction</th>
            <th>Submitted</th>
            <th>Amount</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {transactions.map((t) => (
            <tr key={t.transaction_id}>
              <td>
                <strong>#{t.transaction_id}</strong>
              </td>
              <td>{date(t.submitted_at)}</td>
              <td className="tabular">{money(t.amount, t.currency)}</td>
              <td title={!t.status ? 'Loaded before the pipeline existed' : ''}>
                <StatusBadge status={t.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!transactions.length && <div className="empty-table">No transactions yet.</div>}
    </div>
  )
}
