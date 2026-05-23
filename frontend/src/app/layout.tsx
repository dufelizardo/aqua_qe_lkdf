import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import { Providers } from './providers'
import { Sidebar } from '@/components/ui/Sidebar'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'AQuA-QE LKDF v1.4',
  description: 'Layered Keyword-Driven Framework — Cognitive QA Platform',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body className={inter.className}>
        <Providers>
          <div className="app-shell">
            <Sidebar />
            <main className="main-content">
              {children}
            </main>
          </div>
        </Providers>
      </body>
    </html>
  )
}
