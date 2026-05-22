// frontend/src/app/rtm/page.tsx
'use client'
import { useState } from 'react'
import { Shield, CheckCircle2, XCircle, Circle, Search } from 'lucide-react'

const RTM_DATA = [
  { req:'REQ-001', title:'Login deve ser autenticado',    flow:'LoginFlow',        scenario:'ValidLogin',       status:'PASSED',  coverage:95, evidence:3 },
  { req:'REQ-001', title:'Login deve ser autenticado',    flow:'LoginFlow',        scenario:'InvalidLogin',     status:'PASSED',  coverage:95, evidence:2 },
  { req:'REQ-001', title:'Login deve ser autenticado',    flow:'LoginFlow',        scenario:'BlockedUser',      status:'PASSED',  coverage:95, evidence:2 },
  { req:'REQ-002', title:'Cadastro com email único',      flow:'RegisterFlow',     scenario:'SuccessRegister',  status:'PASSED',  coverage:80, evidence:2 },
  { req:'REQ-002', title:'Cadastro com email único',      flow:'RegisterFlow',     scenario:'DuplicateEmail',   status:'PASSED',  coverage:80, evidence:1 },
  { req:'REQ-007', title:'Checkout deve processar pagamento', flow:'CheckoutFlow', scenario:'ValidPayment',     status:'PASSED',  coverage:60, evidence:4 },
  { req:'REQ-007', title:'Checkout deve processar pagamento', flow:'CheckoutFlow', scenario:'GatewayTimeout',   status:'FAILED',  coverage:60, evidence:1 },
  { req:'REQ-007', title:'Checkout deve processar pagamento', flow:'CheckoutFlow', scenario:'InvalidCard',      status:'PENDING', coverage:60, evidence:0 },
  { req:'REQ-011', title:'API de pagamento REST',         flow:'PaymentAPIFlow',   scenario:'CreatePayment',    status:'PASSED',  coverage:40, evidence:2 },
  { req:'WCAG-AA', title:'Conformidade WCAG 2.1 AA',      flow:'AccessibilityFlow',scenario:'ImageAlt',         status:'PASSED',  coverage:100, evidence:5 },
  { req:'WCAG-AA', title:'Conformidade WCAG 2.1 AA',      flow:'AccessibilityFlow',scenario:'ColorContrast',    status:'PASSED',  coverage:100, evidence:3 },
]

const STATUS_ICON: Record<string, React.ReactNode> = {
  PASSED:  <CheckCircle2 className="w-3.5 h-3.5 text-green-400" />,
  FAILED:  <XCircle      className="w-3.5 h-3.5 text-red-400" />,
  PENDING: <Circle       className="w-3.5 h-3.5 text-yellow-400" />,
}

export default function RTMPage() {
  const [search, setSearch] = useState('')
  const rows = RTM_DATA.filter(r =>
    search === '' ||
    r.req.toLowerCase().includes(search.toLowerCase()) ||
    r.title.toLowerCase().includes(search.toLowerCase()) ||
    r.flow.toLowerCase().includes(search.toLowerCase())
  )

  const reqs    = [...new Set(RTM_DATA.map(r => r.req))].length
  const passed  = RTM_DATA.filter(r => r.status === 'PASSED').length
  const total   = RTM_DATA.length
  const coverage = Math.round(passed / total * 100)

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Traceability Matrix</h1>
          <p className="text-sm text-[#8892a4] mt-1">
            {reqs} requisitos · {total} cenários · cobertura {coverage}%
          </p>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 bg-green-900/20 border border-green-700/30 rounded-lg">
          <div className="w-2 h-2 rounded-full bg-green-400" />
          <span className="text-xs font-medium text-green-400">RTM Online</span>
        </div>
      </div>

      {/* Coverage bar */}
      <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-5">
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm font-medium text-white">Cobertura Bidirecional</p>
          <p className="text-2xl font-bold font-mono text-[#4f7cff]">{coverage}%</p>
        </div>
        <div className="h-2 bg-[#181c24] rounded-full overflow-hidden">
          <div className="h-full rounded-full bg-gradient-to-r from-[#4f7cff] to-[#22c55e] transition-all"
               style={{ width: `${coverage}%` }} />
        </div>
        <div className="flex justify-between mt-2 text-xs text-[#4a5568]">
          <span>0%</span><span>Meta: 80%</span><span>100%</span>
        </div>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#4a5568]" />
        <input value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Buscar por requisito, flow ou cenário..."
          className="w-full pl-9 pr-4 py-2 bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-lg text-sm text-white placeholder-[#4a5568] focus:outline-none focus:border-[#4f7cff]" />
      </div>

      {/* RTM Table */}
      <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[rgba(255,255,255,0.07)]">
              {['Requisito', 'Título', 'Flow', 'Scenario', 'Cobertura', 'Evidências', 'Status'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium text-[#8892a4] uppercase tracking-wider">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-[rgba(255,255,255,0.04)] hover:bg-[#181c24] transition-colors">
                <td className="px-4 py-2.5 font-mono text-xs text-[#4f7cff] font-medium">{row.req}</td>
                <td className="px-4 py-2.5 text-[#8892a4] max-w-[180px] truncate text-xs" title={row.title}>{row.title}</td>
                <td className="px-4 py-2.5 text-white text-xs">{row.flow}</td>
                <td className="px-4 py-2.5 text-[#8892a4] text-xs">{row.scenario}</td>
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-2">
                    <div className="w-16 h-1 bg-[#181c24] rounded-full overflow-hidden">
                      <div className="h-full rounded-full"
                           style={{ width:`${row.coverage}%`, background: row.coverage>=80?'#22c55e':row.coverage>=50?'#f59e0b':'#ef4444' }} />
                    </div>
                    <span className="text-xs text-[#8892a4]">{row.coverage}%</span>
                  </div>
                </td>
                <td className="px-4 py-2.5">
                  <span className={`text-xs font-mono ${row.evidence > 0 ? 'text-white' : 'text-[#4a5568]'}`}>{row.evidence}</span>
                </td>
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-1.5">
                    {STATUS_ICON[row.status]}
                    <span className={`text-xs ${row.status==='PASSED'?'text-green-400':row.status==='FAILED'?'text-red-400':'text-yellow-400'}`}>
                      {row.status}
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
