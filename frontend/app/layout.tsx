import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'DailyOps AI – Dashboard',
  description: 'Voice-first productivity assistant dashboard',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-slate-950 text-slate-100">
        <nav className="bg-slate-900 border-b border-slate-800 p-4">
          <div className="max-w-7xl mx-auto flex justify-between items-center">
            <a href="/" className="text-xl font-bold">DailyOps AI</a>
            <div className="flex gap-4">
              <a href="/" className="hover:text-slate-300">Overview</a>
              <a href="/plans" className="hover:text-slate-300">Plans</a>
              <a href="/logs" className="hover:text-slate-300">Logs</a>
              <a href="/settings" className="hover:text-slate-300">Settings</a>
            </div>
          </div>
        </nav>
        <main className="max-w-7xl mx-auto p-4">
          {children}
        </main>
      </body>
    </html>
  )
}
