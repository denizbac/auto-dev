import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'SaaS Starter Kit - Launch Your Product Fast',
  description: 'Production-ready Next.js SaaS starter with authentication, payments, and database. Skip weeks of setup.',
  keywords: ['saas', 'starter kit', 'nextjs', 'typescript', 'stripe', 'authentication'],
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
