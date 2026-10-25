'use client'
import { Check, CheckCircle2, Flag, XCircle } from 'lucide-react'
import type { CustomerStatus, Decision } from '@/lib/types'
import { toInr } from '@/lib/currency'

// Amounts arrive from the API in dataset dollars; they are shown in rupees with Indian digit grouping (ADR-029).
export const money = (usd: number, currency = 'USD') =>
  currency === 'USD'
    ? new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(toInr(usd))
    : new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(usd)

export const date = (value: string) => (
  <time title={new Date(value).toUTCString()}>
    {new Date(value).toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    })}
  </time>
)

// Customer-facing wording (ADR-028). cls/banner reuse the decision styles; the customer never sees "flag" or "block".
export const statusMeta: Record<CustomerStatus, { label: string; decision: Decision; icon: typeof Check }> = {
  approved: { label: 'Approved', decision: 'allow', icon: CheckCircle2 },
  under_review: { label: 'Under review', decision: 'flag', icon: Flag },
  declined: { label: 'Declined', decision: 'block', icon: XCircle },
}

export const decisionMeta: Record<Decision, { label: string; cls: string; icon: typeof Check }> = {
  allow: { label: 'Allowed', cls: 'decision-allow', icon: CheckCircle2 },
  flag: { label: 'Flagged', cls: 'decision-flag', icon: Flag },
  block: { label: 'Blocked', cls: 'decision-block', icon: XCircle },
}
