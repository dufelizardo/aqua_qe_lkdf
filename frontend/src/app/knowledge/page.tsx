// frontend/src/app/knowledge/page.tsx
'use client'
import { BookOpen, TrendingUp, Shield, Lightbulb } from 'lucide-react'

const PATTERNS = [
  { title:'Authentication_TokenExpiration', domain:'authentication', freq:8,  confidence:0.90, severity:'P1', type:'defect_pattern' },
  { title:'Payments_GatewayTimeout',        domain:'payments',       freq:5,  confidence:0.85, severity:'P0', type:'defect_pattern' },
  { title:'Authorization_DirectURLAccess',  domain:'authorization',  freq:12, confidence:0.95, severity:'P0', type:'defect_pattern' },
  { title:'Forms_InlineValidation',         domain:'forms',          freq:15, confidence:0.88, severity:'—',  type:'best_practice'  },
  { title:'API_ConcurrentRequests',         domain:'api',            freq:6,  confidence:0.75, severity:'P1', type:'failure_mode'   },
]

const TYPE_COLOR: Record<string, string> = {
  defect_pattern: 'text-red-400 bg-red-900/10 border-red-700/20',
  best_practice:  'text-green-400 bg-green-900/10 border-green-700/20',
  failure_mode:   'text-orange-400 bg-orange-900/10 border-orange-700/20',
}

export default function KnowledgePage() {
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-white">Knowledge Layer</h1>
        <p className="text-sm text-[#8892a4] mt-1">Memória organizacional · Padrões aprendidos · Sugestões preventivas</p>
      </div>

      <div className="grid grid-cols-4 gap-4">
        {[
          { label:'Memórias', value:'5',    icon: BookOpen,   color:'text-[#4f7cff]' },
          { label:'Domínios', value:'5',    icon: Shield,     color:'text-[#06b6d4]' },
          { label:'Padrões',  value:'3',    icon: TrendingUp, color:'text-red-400' },
          { label:'Sugestões ativas', value:'8', icon: Lightbulb, color:'text-yellow-400' },
        ].map(c => (
          <div key={c.label} className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-4 flex items-center gap-3">
            <c.icon className={`w-8 h-8 ${c.color}`} />
            <div>
              <p className={`text-2xl font-bold font-mono ${c.color}`}>{c.value}</p>
              <p className="text-xs text-[#8892a4]">{c.label}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-5">
        <p className="text-xs text-[#8892a4] uppercase tracking-widest mb-4">Padrões aprendidos</p>
        <div className="space-y-2">
          {PATTERNS.map((p, i) => (
            <div key={i} className="flex items-center gap-4 p-3 bg-[#181c24] border border-[rgba(255,255,255,0.05)] rounded-lg">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white truncate">{p.title}</p>
                <p className="text-xs text-[#8892a4]">{p.domain}</p>
              </div>
              <span className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${TYPE_COLOR[p.type]}`}>
                {p.type.replace('_', ' ')}
              </span>
              {p.severity !== '—' && (
                <span className={`text-xs font-mono font-bold ${p.severity==='P0'?'text-red-400':'text-yellow-400'}`}>{p.severity}</span>
              )}
              <div className="text-right">
                <p className="text-xs font-mono text-white">{Math.round(p.confidence*100)}%</p>
                <p className="text-[10px] text-[#4a5568]">{p.freq}x</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
