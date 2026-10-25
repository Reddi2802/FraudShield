export type Role = 'customer' | 'investigator'
export type Decision = 'allow' | 'flag' | 'block'
export type CaseStatus = 'open' | 'in_review' | 'resolved'
export type Signal = { agent: 'rules' | 'device' | 'behavioral' | 'network'; score: number | null; reason: string; weight: number }
export type Customer = { customer_id: number; name: string; email: string; card1: number; card_type: string | null; billing_region: string | null; typical_amount: number | null; transaction_count: number }
export type CustomerStatus = 'approved' | 'under_review' | 'declined'
// Customer-safe shapes (ADR-028): a status only, never the score, explanation, signals or case id.
export type MyTransaction = { transaction_id: number; amount: number; currency: string; submitted_at: string; status: CustomerStatus | null }
export type TransactionResult = { transaction_id: number; amount: number; currency: string; submitted_at: string; status: CustomerStatus; message: string }
export type CaseSummary = { case_id: number; transaction_id: number; status: CaseStatus; opened_at: string; decision: Decision | null; risk_score: number | null }
export type CaseDetail = { case_id: number; transaction_id: number; status: CaseStatus; opened_at: string; resolved_at: string | null; transaction: { amount: number; currency: string; submitted_at: string; customer_id: number }; decision: Decision | null; risk_score: number | null; explanation: string | null; feedback: { label: 'fraud' | 'not_fraud'; notes: string | null; investigator_id: number; submitted_at: string } | null; signals?: Signal[] | null }
export type Overview = { customers: number; transactions: number; assessments: number; decisions: Partial<Record<Decision, number>>; cases: Partial<Record<CaseStatus, number>>; feedback: { fraud?: number; not_fraud?: number }; model: null | { type: string; trained_at: string; artifact_path: string; metrics: { pr_auc_lift?: number; roc_auc?: number; flag_precision?: number; flag_recall?: number; base_rate?: number; n?: number } }; retraining: { labels_since_model: number; threshold: number; reached: boolean } }
