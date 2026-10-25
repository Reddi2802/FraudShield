import type { CaseDetail, CaseSummary, Customer, MyTransaction, Overview, Role, TransactionResult } from './types'
import { mockCaseDetail, mockCases, mockCustomer, mockOverview, mockResponse, mockTransactions } from './mocks'

// All network access lives in this file. NEXT_PUBLIC_* values are inlined at build time, and only when
// written literally as process.env.NEXT_PUBLIC_X (reading them through globalThis.process.env does NOT work).
// Default: same-origin ("") because FastAPI serves this site, so there is no CORS and no config to set.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? ''
// Mock data is OPT-IN (NEXT_PUBLIC_USE_MOCK=true, for UI work without a backend). It is never the default.
const USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK === 'true'

export const TOKEN_KEY = 'fraudshield_token'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let token = ''
export function setToken(value: string) {
  token = value
}
function currentToken(): string {
  if (token) return token
  if (typeof window !== 'undefined') return window.sessionStorage.getItem(TOKEN_KEY) ?? ''
  return ''
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (USE_MOCK) return mockRequest<T>(path, options)
  const bearer = currentToken()
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(bearer ? { Authorization: `Bearer ${bearer}` } : {}),
        ...(options.headers || {}),
      },
    })
  } catch {
    throw new ApiError(0, 'Cannot reach the API. Is the server running?')
  }
  if (res.status === 401 && path !== '/auth/login') {
    token = ''
    window.sessionStorage.clear()
    window.sessionStorage.setItem('fraudshield_flash_error', 'Your session expired. Log in again.')
    window.location.hash = '#/login'
    throw new ApiError(401, 'Your session expired. Log in again.')
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const detail = typeof body.detail === 'string' ? body.detail : Array.isArray(body.detail) ? body.detail.map((d: { msg: string }) => d.msg).join('; ') : ''
    throw new ApiError(res.status, detail || 'Something went wrong. Please try again.')
  }
  return res.json()
}

// ---- mock layer: only reachable when USE_MOCK ----
let mockTransactionState = [...mockTransactions]
const mockCaseState = [...mockCases]
async function mockRequest<T>(path: string, options: RequestInit): Promise<T> {
  await new Promise((r) => setTimeout(r, 220))
  if (path === '/auth/login') {
    return { access_token: 'demo-token', token_type: 'bearer', role: JSON.parse(String(options.body)).role, user_id: 1 } as T
  }
  if (path === '/customers/me') return mockCustomer as T
  if (path === '/transactions/me' && options.method === 'POST') {
    const next = {
      ...mockResponse,
      transaction_id: Math.max(...mockTransactionState.map((t) => t.transaction_id), mockResponse.transaction_id) + 1,
      amount: Number(JSON.parse(String(options.body)).amount),
    }
    mockTransactionState = [next, ...mockTransactionState]
    return next as T
  }
  if (path === '/transactions/me') return mockTransactionState as T
  if (path.startsWith('/cases/') && options.method === 'POST') return { feedback_id: 1, case_id: 1, label: 'fraud', notes: null, status: 'resolved' } as T
  if (path.startsWith('/cases/')) return mockCaseDetail as T
  if (path.startsWith('/cases')) return mockCaseState.filter((c) => !path.includes('status=') || path.includes(`status=${c.status}`)) as T
  return mockOverview as T
}

export interface SubmitBody {
  amount: number
  product_cd?: string
  device_type?: string
  device_info?: string
  browser?: string
}

export const api = {
  login: (email: string, password: string, role: Role) =>
    request<{ access_token: string; token_type: 'bearer'; role: Role; user_id: number }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password, role }),
    }),
  customer: () => request<Customer>('/customers/me'),
  transactions: () => request<MyTransaction[]>('/transactions/me'),
  submitTransaction: (body: SubmitBody) =>
    request<TransactionResult>('/transactions/me', { method: 'POST', body: JSON.stringify(body) }),
  cases: (status: string) => request<CaseSummary[]>(`/cases?status=${status}`),
  caseDetail: (id: number) => request<CaseDetail>(`/cases/${id}`),
  feedback: (id: number, body: { label: 'fraud' | 'not_fraud'; notes?: string }) =>
    request(`/cases/${id}/feedback`, { method: 'POST', body: JSON.stringify(body) }),
  overview: () => request<Overview>('/admin/overview'),
}
