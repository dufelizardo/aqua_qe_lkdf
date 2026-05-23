'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard, GitBranch, Play, Shield, Activity,
  Brain, Accessibility, BookOpen, Settings,
} from 'lucide-react'

const NAV: any[] = [
  { section: 'Platform' },
  { href: '/',              label: 'Overview',         icon: LayoutDashboard, dot: 'success' },
  { href: '/flows',         label: 'Flows & Scenarios', icon: GitBranch,       dot: 'success' },
  { href: '/executions',    label: 'Executions',        icon: Play,            dot: 'warning' },
  { href: '/rtm',           label: 'Traceability RTM',  icon: Shield,          dot: 'success' },
  { section: 'Cognitive' },
  { href: '/cognitive',     label: 'Cognitive Engine',  icon: Brain,           dot: 'success' },
  { href: '/accessibility', label: 'Accessibility',     icon: Accessibility,   dot: 'success' },
  { href: '/knowledge',     label: 'Knowledge Layer',   icon: BookOpen,        dot: 'success' },
  { section: 'System' },
  { href: '/settings',      label: 'Settings',          icon: Settings },
]

const DOT_COLOR: Record<string, string> = {
  success: '#22c55e',
  warning: '#f59e0b',
}

export function Sidebar() {
  const pathname = usePathname()

  return (
    <aside className="sidebar">
      {/* Logo */}
      <div style={{ padding: '16px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 8,
            background: 'linear-gradient(135deg, #4f7cff, #7c5cfc)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <span style={{ fontSize: 11, fontWeight: 900, color: 'white' }}>AQ</span>
          </div>
          <div>
            <p style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.2 }}>AQuA-QE</p>
            <p style={{ fontSize: 10, color: 'var(--text-muted)' }}>LKDF v1.4</p>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, overflowY: 'auto', padding: '12px 8px' }}>
        {NAV.map((item, i) => {
          if (item.section) {
            return (
              <p key={i} className="nav-section">{item.section}</p>
            )
          }
          const Icon = item.icon
          const active = pathname === item.href ||
            (item.href !== '/' && pathname?.startsWith(item.href))
          return (
            <Link key={i} href={item.href} className={`nav-item ${active ? 'active' : ''}`}>
              <Icon size={16} style={{ flexShrink: 0 }} />
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {item.label}
              </span>
              {item.dot && (
                <div style={{
                  width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
                  background: DOT_COLOR[item.dot],
                  boxShadow: item.dot === 'success' ? '0 0 5px #22c55e' : 'none',
                }} />
              )}
            </Link>
          )
        })}
      </nav>

      {/* Badge */}
      <div style={{ margin: '0 12px 12px', padding: 12, background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#22c55e' }} />
          <span style={{ fontSize: 10, fontWeight: 600, color: '#22c55e' }}>MVP 3 · Ativo</span>
        </div>
        <p style={{ fontSize: 9, color: 'var(--text-muted)', lineHeight: 1.6 }}>
          581 testes passando<br />
          API · Cypress · Selenium · React
        </p>
      </div>
    </aside>
  )
}
