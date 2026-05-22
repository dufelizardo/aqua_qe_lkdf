// frontend/src/app/executions/page.tsx
'use client'
import { useState } from 'react'
import { Play, Clock, CheckCircle2, XCircle, Activity, RefreshCw } from 'lucide-react'

const MOCK_EXECUTIONS = [
  { id:'e1', flow:'LoginFlow',       req:'REQ-001', adapter:'playwright', status:'PASSED',  passed:3, failed:0, total:3, duration:2340, time:'há 2min' },
  { id:'e2', flow:'CheckoutFlow',    req:'REQ-007', adapter:'api',        status:'FAILED',  passed:4, failed:1, total:5, duration:5120, time:'há 8min' },
  { id:'e3', flow:'RegisterFlow',    req:'REQ-002', adapter:'playwright', status:'PASSED',  passed:2, failed:0, total:2, duration:1890, time:'há 15min' },
  { id:'e4', flow:'AccessibilityFlow', req:'WCAG-AA', adapter:'playwright', status:'PASSED', passed:7, failed:0, total:7, duration:6750, time:'há 1h' },
  { id:'e5', flow:'PaymentAPIFlow',  req:'REQ-011', adapter:'api',        status:'RUNNING', passed:2, failed:0, total:6, duration:0,    time:'agora' },
]

const STATUS_ICON: Record<string, React.ReactNode> = {
  PASSED:  <CheckCircle2 className="w-4 h-4 text-green-400" />,
  FAILED:  <XCircle      className="w-4 h-4 text-red-400" />,
  RUNNING: <Activity     className="w-4 h-4 text-blue-400 animate-pulse" />,
}

export default function ExecutionsPage() {
  const [filter, setFilter] = useState('all')

  const execs = MOCK_EXECUTIONS.filter(e => filter === 'all' || e.status === filter)

  const total  = MOCK_EXECUTIONS.length
  const passed = MOCK_EXECUTIONS.filter(e => e.status === 'PASSED').length
  const failed = MOCK_EXECUTIONS.filter(e => e.status === 'FAILED').length
  const rate   = total ? Math.round(passed / (total - 1) * 100) : 0  // exclude running

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Executions</h1>
          <p className="text-sm text-[#8892a4] mt-1">Histórico de execuções do pipeline</p>
        </div>
        <button className="flex items-center gap-2 px-3 py-2 border border-[rgba(255,255,255,0.1)] text-[#8892a4] hover:text-white text-sm rounded-lg transition-colors">
          <RefreshCw className="w-4 h-4" /> Atualizar
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label:'Total',          value: total,  color:'text-white' },
          { label:'Passaram',       value: passed, color:'text-green-400' },
          { label:'Falharam',       value: failed, color:'text-red-400' },
          { label:'Taxa de sucesso',value:`${rate}%`, color:'text-[#4f7cff]' },
        ].map(card => (
          <div key={card.label} className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-4">
            <p className="text-xs text-[#8892a4] mb-1">{card.label}</p>
            <p className={`text-2xl font-bold font-mono ${card.color}`}>{card.value}</p>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex gap-2">
        {['all','PASSED','FAILED','RUNNING'].map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={`px-3 py-1.5 text-xs rounded-lg border transition-colors font-medium
              ${filter === f ? 'bg-[#4f7cff] border-[#4f7cff] text-white' : 'border-[rgba(255,255,255,0.07)] text-[#8892a4] hover:text-white'}`}>
            {f === 'all' ? 'Todas' : f}
          </button>
        ))}
      </div>

      {/* Executions table */}
      <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[rgba(255,255,255,0.07)]">
              {['Flow', 'Requisito', 'Adapter', 'Scenarios', 'Duração', 'Quando', 'Status'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium text-[#8892a4] uppercase tracking-wider">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {execs.map((e, i) => (
              <tr key={e.id} className={`border-b border-[rgba(255,255,255,0.04)] hover:bg-[#181c24] transition-colors ${i === execs.length-1 ? 'border-0' : ''}`}>
                <td className="px-4 py-3 font-medium text-white">{e.flow}</td>
                <td className="px-4 py-3 text-[#8892a4] font-mono text-xs">{e.req}</td>
                <td className="px-4 py-3">
                  <span className="px-2 py-0.5 bg-[#181c24] border border-[rgba(255,255,255,0.07)] rounded text-[10px] text-[#8892a4]">{e.adapter}</span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-1.5 bg-[#181c24] rounded-full overflow-hidden w-20">
                      <div className="h-full rounded-full bg-green-500"
                           style={{ width: `${e.total > 0 ? (e.passed/e.total*100) : 0}%` }} />
                    </div>
                    <span className="text-xs text-[#8892a4]">{e.passed}/{e.total}</span>
                  </div>
                </td>
                <td className="px-4 py-3 text-[#8892a4] font-mono text-xs">
                  {e.duration > 0 ? `${(e.duration/1000).toFixed(1)}s` : '—'}
                </td>
                <td className="px-4 py-3 text-xs text-[#4a5568]">{e.time}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1.5">
                    {STATUS_ICON[e.status] ?? null}
                    <span className={`text-xs font-medium
                      ${e.status === 'PASSED' ? 'text-green-400' : e.status === 'FAILED' ? 'text-red-400' : 'text-blue-400'}`}>
                      {e.status}
                    </span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
