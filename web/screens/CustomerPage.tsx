'use client'
import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, RefreshCw, ShieldCheck, UserRound } from 'lucide-react'
import { api } from '@/lib/api'
import { toInr, toUsd } from '@/lib/currency'
import type { Customer, MyTransaction, TransactionResult } from '@/lib/types'
import { money, statusMeta } from '@/lib/format'
import { Header } from '@/components/Header'
import { TransactionTable } from '@/components/TransactionTable'

export function CustomerPage() {
  const [customer, setCustomer] = useState<Customer | null>(null)
  const [transactions, setTransactions] = useState<MyTransaction[]>([])
  const [result, setResult] = useState<TransactionResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [amount, setAmount] = useState('')
  const [product, setProduct] = useState('') // '' = the customer's usual code, chosen by the server
  const [optional, setOptional] = useState(false)
  const [demo, setDemo] = useState(false)
  const [deviceType, setDeviceType] = useState('')
  const [deviceInfo, setDeviceInfo] = useState('')
  const [browser, setBrowser] = useState('')
  useEffect(() => {
    Promise.all([api.customer(), api.transactions()])
      .then(([c, t]) => {
        setCustomer(c)
        setTransactions(t)
        setAmount(c.typical_amount ? String(Math.round(toInr(c.typical_amount))) : '')
      })
      .catch((e) => setError(e.message))
  }, [])
  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const r = await api.submitTransaction({
        amount: toUsd(Number(amount)), // the form is in rupees; the backend and model work in dataset dollars
        product_cd: product || undefined,
        device_type: deviceType.trim() || undefined,
        device_info: deviceInfo.trim() || undefined,
        browser: browser.trim() || undefined,
      })
      setResult(r)
      const [txs, cust] = await Promise.all([api.transactions(), api.customer()])
      setTransactions(txs)
      setCustomer(cust)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to submit')
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <Header
        title="New transaction"
        action={
          <span className="secure-pill">
            <ShieldCheck /> Live scoring
          </span>
        }
      />
      <div className="content">
        <section className="customer-banner">
          <div className="avatar">
            <UserRound />
          </div>
          <div>
            <p className="eyebrow">Account overview</p>
            <h2>{customer?.name || 'Loading customer…'}</h2>
            <p className="muted-text">{customer?.email}</p>
          </div>
          <div className="account-facts">
            <div>
              <span>Card ID</span>
              <strong>{customer?.card1 ?? '—'}</strong>
            </div>
            <div>
              <span>Card on file</span>
              <strong>{customer?.card_type ? customer.card_type[0].toUpperCase() + customer.card_type.slice(1) : '—'}</strong>
            </div>
            <div>
              <span>Billing region</span>
              <strong>{customer?.billing_region || '—'}</strong>
            </div>
            <div>
              <span>Typical amount</span>
              <strong>{customer?.typical_amount ? money(customer.typical_amount) : '—'}</strong>
            </div>
          </div>
        </section>
        <div className="two-column">
          <section className="panel form-panel">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Step 01</p>
                <h2>Score a transaction</h2>
              </div>
            </div>
            <p className="muted-text">
              Transactions are time-stamped on the dataset's simulated clock (one hour after your latest one), so
              dates fall in the 2017-18 window.
            </p>
            <form onSubmit={submit} className="transaction-form">
              <label>
                Amount
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  required
                />
                <span className="input-suffix">INR</span>
              </label>
              <button type="button" className="disclosure optional" onClick={() => setOptional(!optional)}>
                {optional ? <ChevronDown /> : <ChevronRight />} Optional device information
              </button>
              {optional && (
                <div className="optional-fields">
                  <label>
                    Device type
                    <input value={deviceType} onChange={(e) => setDeviceType(e.target.value)} placeholder="e.g. mobile" maxLength={100} />
                  </label>
                  <label>
                    Device info
                    <input value={deviceInfo} onChange={(e) => setDeviceInfo(e.target.value)} placeholder="e.g. SM-G960F Build/R16NW" maxLength={255} />
                  </label>
                  <label>
                    Browser
                    <input value={browser} onChange={(e) => setBrowser(e.target.value)} placeholder="e.g. chrome 63.0" maxLength={100} />
                  </label>
                </div>
              )}
              <button type="button" className="disclosure optional" onClick={() => setDemo(!demo)}>
                {demo ? <ChevronDown /> : <ChevronRight />} Demo controls
              </button>
              {demo && (
                <div className="optional-fields">
                  <label>
                    Dataset product code
                    <select value={product} onChange={(e) => setProduct(e.target.value)}>
                      <option value="">Customer's usual (default)</option>
                      {['W', 'C', 'R', 'H', 'S'].map((v) => (
                        <option value={v} key={v}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p className="muted-text">
                    W, C, R, H and S are the IEEE-CIS dataset's anonymized product codes; their meaning is not disclosed. A real
                    customer would not choose this: it belongs to the merchant.
                  </p>
                </div>
              )}
              {error && <div className="error-box">{error}</div>}
              <button className="primary-button" disabled={busy}>
                {busy ? 'Assessing transaction…' : 'Assess transaction'}
                <ShieldCheck />
              </button>
            </form>
          </section>
          <section className="panel result-panel">
            {result ? (
              <>
                <div className={`decision-banner ${statusMeta[result.status].decision}`}>
                  <div>
                    {(() => {
                      const Icon = statusMeta[result.status].icon
                      return <Icon />
                    })()}
                    <div>
                      <span>Transaction status</span>
                      <strong>{statusMeta[result.status].label}</strong>
                    </div>
                  </div>
                </div>
                <p className="result-message">{result.message}</p>
                <p className="muted-text">
                  Reference #{result.transaction_id} · {money(result.amount, result.currency)}
                </p>
              </>
            ) : (
              <div className="empty-result">
                <div className="empty-icon">
                  <ShieldCheck />
                </div>
                <h3>Ready when you are</h3>
                <p>Submit a transaction and you will see its status here.</p>
              </div>
            )}
          </section>
        </div>
        <section className="panel history-panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Activity</p>
              <h2>Recent transactions</h2>
            </div>
            <button
              className="icon-button"
              onClick={() => {
                Promise.all([api.transactions(), api.customer()]).then(([t, c]) => {
                  setTransactions(t)
                  setCustomer(c)
                })
              }}
              aria-label="Refresh transactions"
            >
              <RefreshCw />
            </button>
          </div>
          <TransactionTable transactions={transactions} />
        </section>
      </div>
    </>
  )
}
