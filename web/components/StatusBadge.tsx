'use client'
import { statusMeta } from '@/lib/format'
import type { CustomerStatus } from '@/lib/types'

export function StatusBadge({ status }: { status: CustomerStatus | null }) {
  if (!status) return <span className="badge muted">—</span>
  const m = statusMeta[status]
  const Icon = m.icon
  return (
    <span className={`badge decision-${m.decision}`}>
      <Icon />
      {m.label}
    </span>
  )
}
