// frontend/src/app/accessibility/page.tsx
'use client'
import { Shield, CheckCircle2, XCircle, AlertTriangle } from 'lucide-react'

const VIOLATIONS = [
  { rule:'color-contrast',  impact:'serious',  criterion:'1.4.3', element:'button.btn-secondary', desc:'Contraste insuficiente 2.5:1 (mínimo 4.5:1)' },
  { rule:'image-alt',       impact:'critical', criterion:'1.1.1', element:'img.hero-banner',       desc:'Imagem sem texto alternativo' },
  { rule:'label',           impact:'critical', criterion:'1.3.1', element:'input[name=search]',    desc:'Campo sem label associado' },
]

const IMPACT_COLOR: Record<string, string> = {
  critical: 'text-red-400 bg-red-900/20 border-red-700/30',
  serious:  'text-orange-400 bg-orange-900/20 border-orange-700/30',
  moderate: 'text-yellow-400 bg-yellow-900/20 border-yellow-700/30',
}

export default function AccessibilityPage() {
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-white">Accessibility</h1>
        <p className="text-sm text-[#8892a4] mt-1">WCAG 2.1 AA · axe-core · Nielsen Heuristics</p>
      </div>

      {/* Score */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label:'Conformidade AA',  value:'82%',  color:'text-yellow-400' },
          { label:'Violações total',  value:'3',    color:'text-red-400' },
          { label:'Critérios A ✓',    value:'12/14',color:'text-green-400' },
          { label:'Critérios AA ✓',   value:'8/14', color:'text-yellow-400' },
        ].map(c => (
          <div key={c.label} className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-4">
            <p className="text-xs text-[#8892a4] mb-1">{c.label}</p>
            <p className={`text-2xl font-bold font-mono ${c.color}`}>{c.value}</p>
          </div>
        ))}
      </div>

      {/* Gate status */}
      <div className="flex items-center gap-3 p-4 bg-red-900/10 border border-red-700/30 rounded-xl">
        <XCircle className="w-5 h-5 text-red-400 flex-shrink-0" />
        <div>
          <p className="text-sm font-medium text-red-400">WCAG AA Gate: FAILED</p>
          <p className="text-xs text-[#8892a4] mt-0.5">Release bloqueada — 2 violações críticas não resolvidas</p>
        </div>
      </div>

      {/* Violations */}
      <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-5">
        <p className="text-xs text-[#8892a4] uppercase tracking-widest mb-4">Violações Detectadas</p>
        <div className="space-y-3">
          {VIOLATIONS.map((v, i) => (
            <div key={i} className="p-4 bg-[#181c24] border border-[rgba(255,255,255,0.05)] rounded-lg">
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${IMPACT_COLOR[v.impact]}`}>{v.impact}</span>
                  <span className="text-xs font-mono text-[#4f7cff]">WCAG {v.criterion}</span>
                  <span className="text-xs text-[#8892a4]">{v.rule}</span>
                </div>
              </div>
              <p className="text-sm text-white mb-1">{v.desc}</p>
              <p className="text-xs font-mono text-[#4a5568]">{v.element}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
