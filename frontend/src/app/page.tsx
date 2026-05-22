// frontend/src/app/page.tsx
// AQuA-QE LKDF v1.4 — Dashboard

'use client'

import { useQuery } from '@tanstack/react-query'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, LineChart, Line, PieChart, Pie, Cell,
} from 'recharts'
import {
  CheckCircle2, XCircle, AlertTriangle, Activity,
  FlaskConical, GitBranch, Shield, Zap,
} from 'lucide-react'
import { api } from '@/lib/api'

// ── Metric card ────────────────────────────────────────────────────────────

function MetricCard({
  label, value, delta, icon: Icon, color,
}: {
  label: string; value: string | number; delta?: string
  icon: React.ElementType; color: string
}) {
  return (
    <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-[#8892a4] uppercase tracking-widest mb-2">{label}</p>
          <p className="text-3xl font-bold text-white font-mono">{value}</p>
          {delta && <p className="text-xs text-[#22c55e] mt-1">{delta}</p>}
        </div>
        <div className={`p-2 rounded-lg ${color}`}>
          <Icon className="w-5 h-5" />
        </div>
      </div>
    </div>
  )
}

// ── Status badge ──────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    PASSED:  'bg-green-900/30 text-green-400 border border-green-700/30',
    FAILED:  'bg-red-900/30 text-red-400 border border-red-700/30',
    RUNNING: 'bg-blue-900/30 text-blue-400 border border-blue-700/30',
    PENDING: 'bg-yellow-900/30 text-yellow-400 border border-yellow-700/30',
    DRAFT:   'bg-zinc-800 text-zinc-400 border border-zinc-700/30',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider ${map[status] ?? map.DRAFT}`}>
      {status}
    </span>
  )
}

// ── Pipeline visualization ─────────────────────────────────────────────────

const PIPELINE_STAGES = [
  { id: 'req',       label: 'Requirement', done: true  },
  { id: 'semantic',  label: 'Semantic',    done: true  },
  { id: 'scenario',  label: 'Scenario',    done: true  },
  { id: 'execution', label: 'Execution',   done: false, active: true },
  { id: 'assertion', label: 'Assertion',   done: false },
  { id: 'evidence',  label: 'Evidence',    done: false },
  { id: 'rtm',       label: 'RTM',         done: false },
]

function PipelineViz() {
  return (
    <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-5">
      <p className="text-xs text-[#8892a4] uppercase tracking-widest mb-4">
        Semantic Execution Pipeline
      </p>
      <div className="flex items-center gap-0 overflow-x-auto">
        {PIPELINE_STAGES.map((stage, i) => (
          <div key={stage.id} className="flex items-center">
            {i > 0 && (
              <div className={`h-px w-6 flex-shrink-0 ${stage.done ? 'bg-green-600/50' : 'bg-[rgba(255,255,255,0.07)]'}`} />
            )}
            <div className="flex flex-col items-center min-w-[72px]">
              <div className={`
                w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold border-2 flex-shrink-0
                ${stage.done   ? 'border-green-500 bg-green-900/20 text-green-400' : ''}
                ${stage.active ? 'border-blue-500 bg-blue-900/20 text-blue-400 animate-pulse' : ''}
                ${!stage.done && !stage.active ? 'border-[rgba(255,255,255,0.1)] bg-transparent text-zinc-600' : ''}
              `}>
                {stage.done ? '✓' : i + 1}
              </div>
              <span className="text-[10px] text-[#8892a4] mt-1.5 text-center leading-tight">
                {stage.label}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Coverage chart ─────────────────────────────────────────────────────────

const MOCK_COVERAGE = [
  { name: 'REQ-001', coverage: 95, status: 'PASSED' },
  { name: 'REQ-002', coverage: 80, status: 'PASSED' },
  { name: 'REQ-003', coverage: 100, status: 'PASSED' },
  { name: 'REQ-004', coverage: 60, status: 'PENDING' },
  { name: 'REQ-005', coverage: 30, status: 'FAILED' },
  { name: 'REQ-006', coverage: 0,  status: 'DRAFT' },
]

const COLORS = ['#22c55e', '#4f7cff', '#f59e0b', '#ef4444']

// ── Activity feed ──────────────────────────────────────────────────────────

const MOCK_ACTIVITY = [
  { id: 1, color: '#22c55e', text: '<b>LoginFlow</b> executado — 3 cenários passaram',      time: 'há 2min' },
  { id: 2, color: '#4f7cff', text: '<b>REQ-003</b> convertido em Flow automaticamente',      time: 'há 8min' },
  { id: 3, color: '#f59e0b', text: '<b>CheckoutFlow</b> — 1 cenário falhou em assertion',    time: 'há 15min' },
  { id: 4, color: '#22c55e', text: '<b>RTM</b> atualizado — cobertura 72%',                  time: 'há 1h' },
  { id: 5, color: '#06b6d4', text: '<b>WCAG AA</b> scan concluído — 0 violações críticas',   time: 'há 2h' },
  { id: 6, color: '#a855f7', text: '<b>Knowledge Layer</b> aprendeu 3 novos padrões',        time: 'há 3h' },
]

// ── Main dashboard ─────────────────────────────────────────────────────────

export default function Dashboard() {
  const { data: rtmSummary } = useQuery({
    queryKey: ['rtm-summary'],
    queryFn:  () => api.get('/rtm/summary').then(r => r.data),
    refetchInterval: 30_000,
  })

  const totalReqs     = rtmSummary?.length ?? 12
  const passedReqs    = rtmSummary?.filter((r: any) => r.last_status === 'PASSED').length ?? 8
  const coverage      = totalReqs ? Math.round(passedReqs / totalReqs * 100) : 72

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Dashboard</h1>
          <p className="text-sm text-[#8892a4] mt-1">
            AQuA-QE LKDF v1.4 · Runtime Online · MVP 3
          </p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-[#4f7cff] hover:bg-[#3d6be0] text-white text-sm font-medium rounded-lg transition-colors">
          <Zap className="w-4 h-4" />
          Novo Flow
        </button>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-4 gap-4">
        <MetricCard
          label="Requisitos" value={totalReqs} delta="↑ 3 esta semana"
          icon={GitBranch} color="bg-blue-900/20 text-blue-400"
        />
        <MetricCard
          label="Cobertura RTM" value={`${coverage}%`} delta="↑ 12% vs semana"
          icon={Shield} color="bg-green-900/20 text-green-400"
        />
        <MetricCard
          label="Execuções hoje" value={34} delta="88% taxa de sucesso"
          icon={Activity} color="bg-purple-900/20 text-purple-400"
        />
        <MetricCard
          label="Flows ativos" value={7} delta="↑ 2 esta semana"
          icon={FlaskConical} color="bg-teal-900/20 text-teal-400"
        />
      </div>

      {/* Pipeline */}
      <PipelineViz />

      {/* Charts + Activity */}
      <div className="grid grid-cols-3 gap-4">
        {/* Coverage bar chart */}
        <div className="col-span-2 bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-5">
          <p className="text-xs text-[#8892a4] uppercase tracking-widest mb-4">
            Cobertura por Requisito
          </p>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={MOCK_COVERAGE} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey="name" tick={{ fill: '#8892a4', fontSize: 11 }} />
              <YAxis tick={{ fill: '#8892a4', fontSize: 11 }} domain={[0, 100]} />
              <Tooltip
                contentStyle={{ background: '#1e2230', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8 }}
                labelStyle={{ color: '#e8eaf0' }}
                itemStyle={{ color: '#4f7cff' }}
              />
              <Bar dataKey="coverage" radius={[4, 4, 0, 0]}>
                {MOCK_COVERAGE.map((entry, i) => (
                  <Cell key={i} fill={
                    entry.coverage >= 80 ? '#22c55e' :
                    entry.coverage >= 50 ? '#f59e0b' : '#ef4444'
                  } />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Activity feed */}
        <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-5">
          <p className="text-xs text-[#8892a4] uppercase tracking-widest mb-4">
            Atividade recente
          </p>
          <div className="space-y-2">
            {MOCK_ACTIVITY.map(item => (
              <div key={item.id} className="flex items-start gap-2.5 py-2 border-b border-[rgba(255,255,255,0.04)] last:border-0">
                <div className="w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0"
                     style={{ background: item.color }} />
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-[#8892a4] leading-relaxed"
                     dangerouslySetInnerHTML={{ __html: item.text
                       .replace(/<b>/g, '<span class="text-white font-medium">')
                       .replace(/<\/b>/g, '</span>') }}
                  />
                </div>
                <span className="text-[10px] text-[#4a5568] flex-shrink-0">{item.time}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
