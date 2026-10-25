import type { CaseDetail, CaseSummary, Customer, MyTransaction, Overview, Signal, TransactionResult } from './types'
const now = Date.now()
export const mockCustomer: Customer = { customer_id: 10482, name: 'Avery Morgan', email: 'seed.customer.00001@example.invalid', card1: 4242, card_type: 'credit', billing_region: 'US · California', typical_amount: 86.5, transaction_count: 128 }
export const mockSignals: Signal[] = [
 { agent: 'rules', score: .08, reason: 'Amount and product are consistent with account history.', weight: .35 },
 { agent: 'device', score: .22, reason: 'Known device fingerprint with a recent browser update.', weight: .2 },
 { agent: 'behavioral', score: .47, reason: 'Purchase is slightly above the customer’s typical amount.', weight: .25 },
 { agent: 'network', score: null, reason: 'No network reputation signal available for this request.', weight: .2 },
]
export const mockTransactions: MyTransaction[] = [
 { transaction_id: 843921, amount: 124.8, currency: 'USD', submitted_at: new Date(now - 1000 * 60 * 8).toISOString(), status: 'approved' },
 { transaction_id: 843884, amount: 940, currency: 'USD', submitted_at: new Date(now - 1000 * 60 * 60 * 5).toISOString(), status: 'under_review' },
 { transaction_id: 843201, amount: 62.2, currency: 'USD', submitted_at: new Date(now - 1000 * 60 * 60 * 26).toISOString(), status: null },
]
export const mockResponse: TransactionResult = { transaction_id: 843998, amount: 86.5, currency: 'USD', submitted_at: new Date().toISOString(), status: 'approved', message: 'Your transaction was approved.' }
export const mockCases: CaseSummary[] = [
 { case_id: 22041, transaction_id: 843884, status: 'open', opened_at: new Date(now - 1000 * 60 * 60 * 5).toISOString(), decision: 'flag', risk_score: .59 },
 { case_id: 22037, transaction_id: 843761, status: 'open', opened_at: new Date(now - 1000 * 60 * 60 * 11).toISOString(), decision: 'block', risk_score: .91 },
 { case_id: 21998, transaction_id: 843102, status: 'in_review', opened_at: new Date(now - 1000 * 60 * 60 * 30).toISOString(), decision: 'flag', risk_score: .53 },
 { case_id: 21876, transaction_id: 841900, status: 'resolved', opened_at: new Date(now - 1000 * 60 * 60 * 92).toISOString(), decision: 'block', risk_score: .86 },
]
export const mockCaseDetail: CaseDetail = { case_id: 22041, transaction_id: 843884, status: 'open', opened_at: mockCases[0].opened_at, resolved_at: null, transaction: { amount: 940, currency: 'USD', submitted_at: mockCases[0].opened_at, customer_id: 10482 }, decision: 'flag', risk_score: .59, explanation: 'A few signals need a closer look before this is approved. Evidence: behavioral=0.74 amount_delta=3.2x', feedback: null, signals: mockSignals }
export const mockOverview: Overview = { customers: 2481, transactions: 18642, assessments: 15420, decisions: { allow: 11482, flag: 2824, block: 1114 }, cases: { open: 18, in_review: 12, resolved: 387 }, feedback: { fraud: 102, not_fraud: 285 }, model: { type: 'Gradient boosted trees', trained_at: new Date(now - 1000 * 60 * 60 * 24 * 8).toISOString(), artifact_path: 'models/fraud-v12.bin', metrics: { pr_auc_lift: 3.8, roc_auc: .94, flag_precision: .81, flag_recall: .68 } }, retraining: { labels_since_model: 174, threshold: 250, reached: false } }
