'use client'

import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { CheckCircle2, XCircle, Activity, GitBranch, Shield, FlaskConical, Zap } from 'lucide-react'
import Link from 'next/link'
import { api } from '@/lib/api'

// ── Mock data ──────────────────────────────────────────────────────────────
const COVERAGE_DATA = [
  { name: 'REQ-001', coverage: 95 },
  { name: 'REQ-002', coverage: 80 },
  { name: 'REQ-003', coverage: 100 },
  { name: 'REQ-004', coverage: 60 },
  { name: 'REQ-005', coverage: 30 },
  { name: 'REQ-006', coverage: 0 },
]

const ACTIVITY = [
  { color: '#22c55e', text: 'LoginFlow executado — 3 cenários passaram',      time: 'há 2min' },
  { color: '#4f7cff', text: 'REQ-003 convertido em Flow automaticamente',      time: 'há 8min' },
  { color: '#f59e0b', text: 'CheckoutFlow — 1 cenário falhou em assertion',    time: 'há 15min' },
  { color: '#22c55e', text: 'RTM atualizado — cobertura 72%',                  time: 'há 1h' },
  { color: '#06b6d4', text: 'WCAG AA scan concluído — 0 violações críticas',   time: 'há 2h' },
]

const PIPELINE = [
  { label: 'Requirement', done: true },
  { label: 'Semantic',    done: true },
  { label: 'Scenario',    done: true },
  { label: 'Execution',   done: false, active: true },
  { label: 'Assertion',   done: false },
  { label: 'Evidence',    done: false },
  { label: 'RTM',         done: false },
]

// ── Components ─────────────────────────────────────────────────────────────
function MetricCard({ label, value, delta, iconColor, icon: Icon }: any) {
  return (
    <div className="card" style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
      <div>
        <p className="metric-label">{label}</p>
        <p className="metric-value">{value}</p>
        {delta && <p className="metric-delta">{delta}</p>}
      </div>
      <div className="metric-icon" style={{ background: iconColor + '22' }}>
        <Icon size={20} color={iconColor} />
      </div>
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────
export default function Dashboard() {
  const { data: rtm } = useQuery({
    queryKey: ['rtm-summary'],
    queryFn: () => api.get('/rtm/summary').then(r => r.data).catch(() => null),
    refetchInterval: 30000,
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-primary)' }}>Dashboard</h1>
          <p style={{ fontSize: 14, color: 'var(--text-secondary)', marginTop: 4 }}>
            AQuA-QE LKDF v1.4 · Runtime Online · MVP 3
          </p>
        </div>
        <Link href="/flows/new" className="btn-primary">
          <Zap size={16} />
          Novo Flow
        </Link>
      </div>

      {/* Metrics */}
      <div className="card-grid card-grid-4">
        <MetricCard label="Requisitos"     value={12}    delta="↑ 3 esta semana"   iconColor="#4f7cff" icon={GitBranch}    />
        <MetricCard label="Cobertura RTM"  value="72%"   delta="↑ 12% vs semana"   iconColor="#22c55e" icon={Shield}       />
        <MetricCard label="Execuções hoje" value={34}    delta="88% taxa de sucesso" iconColor="#a855f7" icon={Activity}     />
        <MetricCard label="Flows ativos"   value={7}     delta="↑ 2 esta semana"   iconColor="#06b6d4" icon={FlaskConical} />
      </div>

      {/* Pipeline */}
      <div className="card">
        <p style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 20 }}>
          Semantic Execution Pipeline
        </p>
        <div style={{ display: 'flex', alignItems: 'center', overflowX: 'auto' }}>
          {PIPELINE.map((stage, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center' }}>
              {i > 0 && (
                <div className={`pipeline-connector ${stage.done ? 'done' : 'idle'}`} />
              )}
              <div className="pipeline-stage">
                <div className={`pipeline-circle ${stage.done ? 'done' : stage.active ? 'active' : 'idle'}`}>
                  {stage.done ? '✓' : i + 1}
                </div>
                <span className="pipeline-label">{stage.label}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Bottom row */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16 }}>

        {/* Coverage chart */}
        <div className="card">
          <p style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 16 }}>
            Cobertura por Requisito
          </p>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={COVERAGE_DATA} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey="name" tick={{ fill: '#8892a4', fontSize: 11 }} />
              <YAxis tick={{ fill: '#8892a4', fontSize: 11 }} domain={[0, 100]} />
              <Tooltip
                contentStyle={{ background: '#181c24', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8 }}
                labelStyle={{ color: '#e8eaf0' }}
                itemStyle={{ color: '#4f7cff' }}
              />
              <Bar dataKey="coverage" radius={[4, 4, 0, 0]}>
                {COVERAGE_DATA.map((entry, i) => (
                  <Cell key={i} fill={entry.coverage >= 80 ? '#22c55e' : entry.coverage >= 50 ? '#f59e0b' : '#ef4444'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Activity */}
        <div className="card">
          <p style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 16 }}>
            Atividade recente
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {ACTIVITY.map((item, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'flex-start', gap: 10,
                padding: '10px 0',
                borderBottom: i < ACTIVITY.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none',
              }}>
                <div style={{ width: 6, height: 6, borderRadius: '50%', background: item.color, marginTop: 6, flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{item.text}</p>
                </div>
                <span style={{ fontSize: 10, color: 'var(--text-muted)', flexShrink: 0 }}>{item.time}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
