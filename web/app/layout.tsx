import type { Metadata, Viewport } from 'next'
import './globals.css'
export const metadata: Metadata = { title: 'FraudShield · Transaction intelligence', description: 'Fraud detection operations console' }
export const viewport: Viewport = { colorScheme: 'light dark', themeColor: '#f6f8fb' }
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en"><body className="antialiased">{children}</body></html> }
