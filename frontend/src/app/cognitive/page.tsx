// frontend/src/app/cognitive/page.tsx
'use client'
import { useState } from 'react'
import { Brain, Sparkles, AlertTriangle, CheckCircle2, Loader2, ChevronDown, ChevronRight } from 'lucide-react'
import { api } from '@/lib/api'

interface AnalysisResult {
  interpreted_intent?: string
  risk_level?: string
  business_rules?: { description: string }[]
  ambiguities?: string[]
  gaps?: string[]
  suggested_scenarios?: string[]
  generated_flow_dsl?: string
}

export default function CognitivePage() {
  const [text, setText] = useState('O usuário deve ser redirecionado para o dashboard após o login bem-sucedido com credenciais válidas.')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [error, setError]   = useState('')
  const [tab, setTab]       = useState<'analysis'|'dsl'|'ambiguity'>('analysis')

  async function analyze() {
    if (!text.trim()) return
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const res = await api.post('/requirements/analyze', {
        requirement_text: text,
        requirement_id: 'REQ-DEMO',
      })
      setResult(res.data)
    } catch {
      // Demo fallback
      setResult({
        interpreted_intent: 'Redirecionamento pós-autenticação bem-sucedida',
        risk_level: 'HIGH',
        business_rules: [
          { description: 'Credenciais válidas são pré-requisito para o redirecionamento' },
          { description: 'Sessão deve ser criada antes do redirect' },
          { description: 'URL de destino deve ser sanitizada contra open redirect' },
        ],
        ambiguities: [
          '"dashboard" assume instância única — e se houver dashboards por papel?',
          '"bem-sucedido" não está definido — inclui 2FA? Verificação de email?',
          'Tempo de redirecionamento não especificado',
        ],
        gaps: ['Comportamento no primeiro login', 'Login via SSO', 'Conta pendente de verificação'],
        suggested_scenarios: [
          'HappyPath: login com credenciais válidas → redirect para /dashboard',
          'NegativePath: credenciais inválidas → mensagem de erro',
          'EdgeCase: sessão expirada durante navegação → redirect para login',
          'Security: acesso direto a /dashboard sem autenticação → bloqueado',
        ],
        generated_flow_dsl: `# Flow: LoginRedirectFlow\n# Requirement: REQ-DEMO\n# Adapter: playwright\n\n@flow LoginRedirectFlow\n  @scenario ValidLoginRedirect\n    Dado que o usuário está na página de login\n    E que o usuário possui credenciais válidas\n    Quando o usuário insere as credenciais\n    Quando o usuário clica em Entrar\n    Então é esperado que seja redirecionado para o dashboard`,
      })
    } finally {
      setLoading(false)
    }
  }

  const riskColor = result?.risk_level === 'HIGH' ? 'text-red-400' : result?.risk_level === 'MEDIUM' ? 'text-yellow-400' : 'text-green-400'

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-white">Cognitive Engine</h1>
        <p className="text-sm text-[#8892a4] mt-1">Requirement Intelligence · Ambiguity Detection · Scenario Generation</p>
      </div>

      {/* Input */}
      <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-5 space-y-4">
        <p className="text-xs text-[#8892a4] uppercase tracking-widest">Requisito</p>
        <textarea value={text} onChange={e => setText(e.target.value)} rows={3}
          className="w-full bg-[#181c24] border border-[rgba(255,255,255,0.07)] rounded-lg p-3 text-sm text-white resize-none focus:outline-none focus:border-[#4f7cff] placeholder-[#4a5568]"
          placeholder="Insira o requisito em linguagem natural..." />
        <button onClick={analyze} disabled={loading || !text.trim()}
          className="flex items-center gap-2 px-5 py-2 bg-[#4f7cff] hover:bg-[#3d6be0] disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors">
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Brain className="w-4 h-4" />}
          {loading ? 'Analisando...' : 'Analisar com IA'}
        </button>
      </div>

      {/* Results */}
      {result && (
        <div className="space-y-4">
          {/* Summary */}
          <div className="grid grid-cols-3 gap-4">
            <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-4">
              <p className="text-xs text-[#8892a4] mb-1">Risco</p>
              <p className={`text-xl font-bold font-mono ${riskColor}`}>{result.risk_level}</p>
            </div>
            <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-4">
              <p className="text-xs text-[#8892a4] mb-1">Regras extraídas</p>
              <p className="text-xl font-bold font-mono text-white">{result.business_rules?.length ?? 0}</p>
            </div>
            <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-4">
              <p className="text-xs text-[#8892a4] mb-1">Ambiguidades</p>
              <p className="text-xl font-bold font-mono text-yellow-400">{result.ambiguities?.length ?? 0}</p>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex gap-1 border-b border-[rgba(255,255,255,0.07)]">
            {(['analysis','dsl','ambiguity'] as const).map(t => (
              <button key={t} onClick={() => setTab(t)}
                className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors
                  ${tab===t ? 'border-[#4f7cff] text-[#4f7cff]' : 'border-transparent text-[#8892a4] hover:text-white'}`}>
                {t === 'analysis' ? 'Análise' : t === 'dsl' ? 'Flow DSL' : 'Ambiguidades'}
              </button>
            ))}
          </div>

          {tab === 'analysis' && (
            <div className="grid grid-cols-2 gap-4">
              {/* Intent */}
              <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-4">
                <p className="text-xs text-[#8892a4] uppercase tracking-widest mb-3 flex items-center gap-2">
                  <Sparkles className="w-3 h-3" /> Intenção interpretada
                </p>
                <p className="text-sm text-white">{result.interpreted_intent}</p>
              </div>
              {/* Business rules */}
              <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-4">
                <p className="text-xs text-[#8892a4] uppercase tracking-widest mb-3">Regras de negócio</p>
                <div className="space-y-2">
                  {result.business_rules?.map((r, i) => (
                    <div key={i} className="flex items-start gap-2 text-xs text-[#8892a4]">
                      <CheckCircle2 className="w-3 h-3 text-green-400 mt-0.5 flex-shrink-0" />
                      {r.description}
                    </div>
                  ))}
                </div>
              </div>
              {/* Scenarios */}
              <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-4 col-span-2">
                <p className="text-xs text-[#8892a4] uppercase tracking-widest mb-3">Cenários sugeridos</p>
                <div className="grid grid-cols-2 gap-2">
                  {result.suggested_scenarios?.map((s, i) => (
                    <div key={i} className="flex items-start gap-2 p-2.5 bg-[#181c24] rounded-lg text-xs">
                      <ChevronRight className="w-3 h-3 text-[#4f7cff] mt-0.5 flex-shrink-0" />
                      <span className="text-[#8892a4]">{s}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {tab === 'dsl' && (
            <div className="bg-[#0a0c10] border border-[rgba(255,255,255,0.07)] rounded-xl p-5 font-mono text-xs text-[#8892a4] whitespace-pre">
              {result.generated_flow_dsl}
            </div>
          )}

          {tab === 'ambiguity' && (
            <div className="space-y-3">
              {result.ambiguities?.map((a, i) => (
                <div key={i} className="flex items-start gap-3 p-4 bg-yellow-900/10 border border-yellow-700/30 rounded-xl">
                  <AlertTriangle className="w-4 h-4 text-yellow-400 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-[#e8eaf0]">{a}</p>
                </div>
              ))}
              {result.gaps?.map((g, i) => (
                <div key={`gap-${i}`} className="flex items-start gap-3 p-4 bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl">
                  <div className="w-4 h-4 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <div className="w-2 h-2 rounded-full bg-[#4a5568]" />
                  </div>
                  <p className="text-sm text-[#8892a4]">Gap: {g}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
