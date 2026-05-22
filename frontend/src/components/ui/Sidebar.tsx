// frontend/src/components/ui/Sidebar.tsx
'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard, GitBranch, Play, Shield, Activity,
  Brain, Accessibility, BookOpen, Settings, Zap,
} from 'lucide-react'

const NAV_ITEMS = [
  { label: 'Platform',     type: 'section' },
  { href: '/',             label: 'Overview',        icon: LayoutDashboard, status: 'online' },
  { href: '/flows',        label: 'Flows & Scenarios', icon: GitBranch,    status: 'online' },
  { href: '/executions',   label: 'Executions',      icon: Play,           status: 'warn' },
  { href: '/rtm',          label: 'Traceability RTM', icon: Shield,        status: 'online' },
  { label: 'Cognitive',   type: 'section' },
  { href: '/cognitive',    label: 'Cognitive Engine', icon: Brain,         status: 'online' },
  { href: '/accessibility',label: 'Accessibility',   icon: Accessibility, status: 'online' },
  { href: '/knowledge',    label: 'Knowledge Layer',  icon: BookOpen,      status: 'online' },
  { label: 'System',      type: 'section' },
  { href: '/settings',     label: 'Settings',         icon: Settings },
]

export function Sidebar() {
  const pathname = usePathname()
  return (
    <aside className="w-56 flex-shrink-0 bg-[#111318] border-r border-[rgba(255,255,255,0.07)] flex flex-col">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-[rgba(255,255,255,0.07)]">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[#4f7cff] to-[#7c5cfc] flex items-center justify-center">
            <span className="text-xs font-black text-white">AQ</span>
          </div>
          <div>
            <p className="text-sm font-bold text-white leading-tight">AQuA-QE</p>
            <p className="text-[10px] text-[#8892a4]">LKDF v1.4</p>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-3 px-2">
        {NAV_ITEMS.map((item, i) => {
          if (item.type === 'section') {
            return (
              <p key={i} className="px-2 pt-4 pb-1 text-[9px] font-semibold uppercase tracking-widest text-[#4a5568]">
                {item.label}
              </p>
            )
          }
          const Icon    = item.icon!
          const active  = pathname === item.href ||
                          (item.href !== '/' && pathname?.startsWith(item.href!))
          const statusColor = item.status === 'online' ? 'bg-green-400 shadow-[0_0_5px_#22c55e]'
                            : item.status === 'warn'   ? 'bg-yellow-400' : ''
          return (
            <Link key={i} href={item.href!}
              className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm mb-0.5 transition-all group
                ${active
                  ? 'bg-[rgba(79,124,255,0.12)] text-[#4f7cff] border border-[rgba(79,124,255,0.2)]'
                  : 'text-[#8892a4] hover:bg-[#181c24] hover:text-white border border-transparent'
                }`}
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              <span className="flex-1 truncate">{item.label}</span>
              {item.status && (
                <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${statusColor}`} />
              )}
            </Link>
          )
        })}
      </nav>

      {/* MVP badge */}
      <div className="mx-3 mb-3 p-3 bg-[#181c24] border border-[rgba(255,255,255,0.07)] rounded-xl">
        <div className="flex items-center gap-1.5 mb-1.5">
          <div className="w-1.5 h-1.5 rounded-full bg-green-400" />
          <span className="text-[10px] font-semibold text-green-400">MVP 3 · Ativo</span>
        </div>
        <p className="text-[9px] text-[#4a5568] leading-relaxed">
          543 testes passando<br />
          API · Cypress · Selenium · React
        </p>
      </div>
    </aside>
  )
}
