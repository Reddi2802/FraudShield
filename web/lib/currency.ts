// Demo localization (ADR-029). The database, the model and the API stay in the dataset's native
// currency (USD); the website SHOWS rupees at one fixed demo rate and converts rupee input back to
// dollars before sending. This is not a live exchange rate.
export const USD_TO_INR = 95

export const toInr = (usd: number) => usd * USD_TO_INR
// Rounded to 4 decimals so 1 rupee (about 0.0105 USD) survives the trip as a valid positive amount.
export const toUsd = (inr: number) => Math.round((inr / USD_TO_INR) * 10000) / 10000
