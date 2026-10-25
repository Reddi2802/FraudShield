'use client'
import type { Decision } from '@/lib/types'
import { decisionMeta } from '@/lib/format'

export function Badge({ decision }: { decision: Decision | null }) {
  if (!decision) return <span className="badge muted">—</span>
  const m = decisionMeta[decision]
  const Icon = m.icon
  return (
    <span className={`badge ${m.cls}`}>
      <Icon />
      {m.label}
    </span>
  )
}
