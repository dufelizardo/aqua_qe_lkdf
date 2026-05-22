// frontend/src/app/flows/page.tsx
'use client'
import { useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { Play, Plus, Search, Filter, GitBranch, Clock, CheckCircle2, XCircle } from 'lucide-react'
import { api, Flow } from '@/lib/api'

const MOCK_FLOWS: Flow[] = [
  { id:'1', name:'LoginFlow',       requirement_ref:'REQ-001', adapter:'playwright', priority:'HIGH',   dsl_source:'', scenario_count:3, step_count:18, status:'PASSED',  project_id:'p1', created_at:'2026-05-01', updated_at:'2026-05-21' },
  { id:'2', name:'CheckoutFlow',    requirement_ref:'REQ-007', adapter:'api',        priority:'HIGH',   dsl_source:'', scenario_count:5, step_count:31, status:'FAILED',  project_id:'p1', created_at:'2026-05-10', updated_at:'2026-05-21' },
  { id:'3', name:'RegisterFlow',    requirement_ref:'REQ-002', adapter:'playwright', priority:'MEDIUM', dsl_source:'', scenario_count:2, step_count:12, status:'PASSED',  project_id:'p1', created_at:'2026-05-12', updated_at:'2026-05-20' },
  { id:'4', name:'ProfileFlow',     requirement_ref:'REQ-005', adapter:'selenium',   priority:'LOW',    dsl_source:'', scenario_count:4, step_count:22, status:'PENDING', project_id:'p1', created_at:'2026-05-15', updated_at:'2026-05-19' },
  { id:'5', name:'AccessibilityFlow', requirement_ref:'WCAG-AA', adapter:'playwright', priority:'HIGH', dsl_source:'', scenario_count:7, step_count:42, status:'PASSED',  project_id:'p1', created_at:'2026-05-18', updated_at:'2026-05-21' },
  { id:'6', name:'PaymentAPIFlow',  requirement_ref:'REQ-011', adapter:'api',        priority:'HIGH',   dsl_source:'', scenario_count:6, step_count:28, status:'DRAFT',   project_id:'p1', created_at:'2026-05-20', updated_at:'2026-05-21' },
]

const STATUS_STYLE: Record<string, string> = {
  PASSED:  'text-green-400 bg-green-900/20 border-green-700/30',
  FAILED:  'text-red-400 bg-red-900/20 border-red-700/30',
  PENDING: 'text-yellow-400 bg-yellow-900/20 border-yellow-700/30',
  DRAFT:   'text-zinc-400 bg-zinc-800/40 border-zinc-700/30',
}

const ADAPTER_COLOR: Record<string, string> = {
  playwright: '#06b6d4',
  selenium:   '#f59e0b',
  api:        '#a855f7',
  cypress:    '#22c55e',
  robot:      '#4f7cff',
}

export default function FlowsPage() {
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all')

  const flows = MOCK_FLOWS.filter(f =>
    (search === '' || f.name.toLowerCase().includes(search.toLowerCase()) ||
     f.requirement_ref.toLowerCase().includes(search.toLowerCase())) &&
    (filter === 'all' || f.status === filter)
  )

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Flows & Scenarios</h1>
          <p className="text-sm text-[#8892a4] mt-1">{MOCK_FLOWS.length} flows · {MOCK_FLOWS.reduce((a,f) => a+f.scenario_count, 0)} cenários</p>
        </div>
        <Link href="/flows/new" className="flex items-center gap-2 px-4 py-2 bg-[#4f7cff] hover:bg-[#3d6be0] text-white text-sm font-medium rounded-lg transition-colors">
          <Plus className="w-4 h-4" /> Novo Flow
        </Link>
      </div>

      {/* Filters */}
      <div className="flex gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#4a5568]" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Buscar flows ou requisitos..."
            className="w-full pl-9 pr-4 py-2 bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-lg text-sm text-white placeholder-[#4a5568] focus:outline-none focus:border-[#4f7cff]" />
        </div>
        {['all','PASSED','FAILED','PENDING','DRAFT'].map(s => (
          <button key={s} onClick={() => setFilter(s)}
            className={`px-3 py-2 text-xs rounded-lg border transition-colors font-medium
              ${filter === s ? 'bg-[#4f7cff] border-[#4f7cff] text-white' : 'border-[rgba(255,255,255,0.07)] text-[#8892a4] hover:text-white'}`}>
            {s === 'all' ? 'Todos' : s}
          </button>
        ))}
      </div>

      {/* Flow cards */}
      <div className="grid gap-3">
        {flows.map(flow => (
          <Link key={flow.id} href={`/flows/${flow.id}`}
            className="block bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-5 hover:border-[rgba(79,124,255,0.3)] transition-all group">
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-[#181c24] flex items-center justify-center">
                  <GitBranch className="w-4 h-4" style={{ color: ADAPTER_COLOR[flow.adapter] ?? '#8892a4' }} />
                </div>
                <div>
                  <p className="font-semibold text-white group-hover:text-[#4f7cff] transition-colors">{flow.name}</p>
                  <p className="text-xs text-[#8892a4]">{flow.requirement_ref}</p>
                </div>
              </div>
              <span className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${STATUS_STYLE[flow.status]}`}>
                {flow.status}
              </span>
            </div>
            <div className="flex items-center gap-4 text-xs text-[#8892a4]">
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: ADAPTER_COLOR[flow.adapter] }} />
                {flow.adapter}
              </span>
              <span>{flow.scenario_count} scenarios</span>
              <span>{flow.step_count} steps</span>
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" /> {flow.updated_at}
              </span>
              <span className={`ml-auto px-2 py-0.5 rounded text-[10px] font-medium
                ${flow.priority === 'HIGH' ? 'text-red-400 bg-red-900/10' :
                  flow.priority === 'MEDIUM' ? 'text-yellow-400 bg-yellow-900/10' : 'text-zinc-400 bg-zinc-800/30'}`}>
                {flow.priority}
              </span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}
