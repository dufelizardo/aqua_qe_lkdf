// frontend/src/app/flows/[id]/page.tsx
// AQuA-QE LKDF v1.4 — Flow DSL Editor

'use client'

import { useState, useCallback } from 'react'
import dynamic from 'next/dynamic'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Play, Save, RefreshCw, CheckCircle2, XCircle, AlertCircle, Loader2 } from 'lucide-react'
import { api, flowsApi, executionsApi, Flow, Execution } from '@/lib/api'

const MonacoEditor = dynamic(() => import('@monaco-editor/react'), { ssr: false })

// ── Scenario card ─────────────────────────────────────────────────────────

function ScenarioCard({ name, steps, status }: {
  name: string; steps: number; status?: string
}) {
  const color = status === 'PASSED' ? 'border-green-700/40 bg-green-900/10'
              : status === 'FAILED' ? 'border-red-700/40 bg-red-900/10'
              : 'border-[rgba(255,255,255,0.07)] bg-transparent'
  return (
    <div className={`rounded-lg border p-3 cursor-pointer hover:border-blue-500/50 transition-colors ${color}`}>
      <p className="text-sm font-medium text-white">{name}</p>
      <p className="text-xs text-[#8892a4] mt-0.5">{steps} steps</p>
    </div>
  )
}

// ── Step result row ────────────────────────────────────────────────────────

function StepRow({ keyword, text, status, duration }: {
  keyword: string; text: string; status: string; duration?: number
}) {
  const kwColor = {
    Dado:   'text-[#06b6d4]',
    Quando: 'text-[#f59e0b]',
    Então:  'text-[#22c55e]',
    E:      'text-[#8892a4]',
  }[keyword] ?? 'text-[#8892a4]'

  const icon = status === 'passed' ? <CheckCircle2 className="w-4 h-4 text-green-400" />
             : status === 'failed' ? <XCircle      className="w-4 h-4 text-red-400" />
             : status === 'running'? <Loader2      className="w-4 h-4 text-blue-400 animate-spin" />
             : <div className="w-4 h-4 rounded-full border border-zinc-700" />

  return (
    <div className={`flex items-start gap-3 px-4 py-2.5 rounded-lg text-sm transition-colors
      ${status === 'running' ? 'bg-blue-900/10 border border-blue-700/30' :
        status === 'passed'  ? 'bg-green-900/5 border border-green-700/20' :
        status === 'failed'  ? 'bg-red-900/5 border border-red-700/20' :
        'bg-transparent border border-transparent'}`}>
      <div className="mt-0.5 flex-shrink-0">{icon}</div>
      <div className="flex-1 min-w-0">
        <span className={`font-semibold font-mono ${kwColor}`}>{keyword} </span>
        <span className="text-[#e8eaf0]">{text}</span>
        {duration && (
          <span className="ml-2 text-xs text-[#4a5568] font-mono">{duration}ms</span>
        )}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────

const SAMPLE_DSL = `# Flow: LoginFlow
# Requirement: REQ-001 — Login deve ser autenticado
# Adapter: playwright
# Priority: HIGH

@flow LoginFlow
  @scenario ValidLogin
    Dado que o usuário está na página de login
    E que o usuário possui credenciais válidas
    Quando o usuário insere "usuario@empresa.com" no campo email
    E o usuário insere "senha123" no campo senha
    Quando o usuário clica no botão "Entrar"
    Então é esperado que o usuário seja redirecionado para o dashboard
    E é esperado que a mensagem "Login realizado com sucesso" seja exibida

  @scenario InvalidLogin
    Dado que o usuário está na página de login
    Quando o usuário insere "errado@test.com" no campo email
    E o usuário insere "senhaerrada" no campo senha
    Quando o usuário clica no botão "Entrar"
    Então é esperado que a mensagem "Credenciais inválidas" seja exibida`

export default function FlowEditorPage({ params }: { params: { id: string } }) {
  const qc = useQueryClient()
  const [dsl, setDsl]           = useState(SAMPLE_DSL)
  const [tab, setTab]           = useState<'editor' | 'execution'>('editor')
  const [execSteps, setExecSteps] = useState<any[]>([])
  const [execStatus, setExecStatus] = useState<'idle' | 'running' | 'passed' | 'failed'>('idle')
  const [elapsedMs, setElapsedMs] = useState(0)

  const { data: flow } = useQuery({
    queryKey: ['flow', params.id],
    queryFn:  () => params.id === 'new' ? null : flowsApi.get(params.id).then(r => r.data),
    enabled:  params.id !== 'new',
  })

  // Parse DSL
  const { data: parseResult, refetch: reParse, isFetching: isParsing } = useQuery({
    queryKey: ['parse', dsl.slice(0, 50)],
    queryFn:  () => api.post('/flows/parse', { source: dsl }).then(r => r.data),
    enabled:  false,
  })

  // Simulate execution (real would call executionsApi.trigger)
  const runExecution = useCallback(async () => {
    setTab('execution')
    setExecStatus('running')
    setExecSteps([])
    const t0 = Date.now()

    const steps = [
      { keyword: 'Dado', text: 'que o usuário está na página de login' },
      { keyword: 'E',    text: 'que o usuário possui credenciais válidas' },
      { keyword: 'Quando', text: 'o usuário insere "usuario@empresa.com" no campo email' },
      { keyword: 'E',    text: 'o usuário insere "senha123" no campo senha' },
      { keyword: 'Quando', text: 'o usuário clica no botão "Entrar"' },
      { keyword: 'Então', text: 'é esperado que seja redirecionado para o dashboard' },
      { keyword: 'E',    text: 'é esperado que a mensagem seja exibida' },
    ]

    for (let i = 0; i < steps.length; i++) {
      setExecSteps(prev => [...prev, { ...steps[i], status: 'running' }])
      await new Promise(r => setTimeout(r, 300 + Math.random() * 400))
      setExecSteps(prev => prev.map((s, idx) =>
        idx === i ? { ...s, status: 'passed', duration: Math.floor(200 + Math.random() * 500) } : s
      ))
    }
    setElapsedMs(Date.now() - t0)
    setExecStatus('passed')
  }, [])

  // Parse DSL to extract scenarios
  const scenarios = dsl.match(/@scenario\s+(\w+)/g)?.map(s => s.replace('@scenario ', '')) ?? []

  return (
    <div className="flex flex-col h-full gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-white">
            {flow?.name ?? 'Novo Flow'}
          </h1>
          <p className="text-xs text-[#8892a4] mt-0.5">
            {flow?.requirement_ref ?? 'DSL Editor'} · {flow?.adapter ?? 'playwright'}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => reParse()}
            disabled={isParsing}
            className="flex items-center gap-2 px-3 py-1.5 border border-[rgba(255,255,255,0.1)] text-[#8892a4] hover:text-white hover:border-[rgba(255,255,255,0.2)] text-sm rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isParsing ? 'animate-spin' : ''}`} />
            Validar
          </button>
          <button
            onClick={runExecution}
            disabled={execStatus === 'running'}
            className="flex items-center gap-2 px-4 py-1.5 bg-[#4f7cff] hover:bg-[#3d6be0] disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
          >
            <Play className="w-3.5 h-3.5" />
            Executar
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[rgba(255,255,255,0.07)] pb-0">
        {(['editor', 'execution'] as const).map(t => (
          <button key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors
              ${tab === t
                ? 'border-[#4f7cff] text-[#4f7cff]'
                : 'border-transparent text-[#8892a4] hover:text-white'}`}
          >
            {t === 'editor' ? 'DSL Editor' : 'Execução'}
          </button>
        ))}
      </div>

      {tab === 'editor' && (
        <div className="grid grid-cols-[1fr_280px] gap-4 flex-1 min-h-0">
          {/* Monaco Editor */}
          <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl overflow-hidden">
            <MonacoEditor
              height="100%"
              defaultLanguage="yaml"
              value={dsl}
              onChange={v => setDsl(v ?? '')}
              theme="vs-dark"
              options={{
                fontSize: 13,
                minimap: { enabled: false },
                lineNumbers: 'on',
                scrollBeyondLastLine: false,
                wordWrap: 'on',
                padding: { top: 16, bottom: 16 },
                fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
              }}
            />
          </div>

          {/* Side panel */}
          <div className="flex flex-col gap-3 overflow-y-auto">
            {/* Parse status */}
            {parseResult && (
              <div className={`rounded-xl border p-4 ${
                parseResult.valid
                  ? 'border-green-700/30 bg-green-900/10'
                  : 'border-red-700/30 bg-red-900/10'
              }`}>
                <div className="flex items-center gap-2 mb-2">
                  {parseResult.valid
                    ? <CheckCircle2 className="w-4 h-4 text-green-400" />
                    : <XCircle className="w-4 h-4 text-red-400" />
                  }
                  <span className={`text-sm font-medium ${parseResult.valid ? 'text-green-400' : 'text-red-400'}`}>
                    {parseResult.valid ? 'DSL válido' : 'DSL inválido'}
                  </span>
                </div>
                {parseResult.valid && (
                  <div className="text-xs text-[#8892a4] space-y-1">
                    <p>Flow: <span className="text-white">{parseResult.flow_name}</span></p>
                    <p>Scenarios: <span className="text-white">{parseResult.scenarios}</span></p>
                    <p>Steps: <span className="text-white">{parseResult.steps}</span></p>
                  </div>
                )}
                {parseResult.errors?.map((e: string, i: number) => (
                  <p key={i} className="text-xs text-red-400 mt-1">{e}</p>
                ))}
              </div>
            )}

            {/* Detected scenarios */}
            <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-4">
              <p className="text-xs text-[#8892a4] uppercase tracking-widest mb-3">Scenarios</p>
              <div className="space-y-2">
                {scenarios.length > 0
                  ? scenarios.map(s => (
                      <ScenarioCard key={s} name={s} steps={3} />
                    ))
                  : <p className="text-xs text-[#4a5568]">Nenhum scenario detectado.</p>
                }
              </div>
            </div>

            {/* LKDF Layers */}
            <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-4">
              <p className="text-xs text-[#8892a4] uppercase tracking-widest mb-3">LKDF Layers</p>
              <div className="space-y-2">
                {[
                  { name: 'POM Layer',      color: '#06b6d4' },
                  { name: 'Flow Layer',     color: '#4f7cff' },
                  { name: 'Scenario Layer', color: '#a855f7' },
                  { name: 'Test Layer',     color: '#22c55e' },
                ].map(layer => (
                  <div key={layer.name} className="flex items-center gap-3 p-2 bg-[#181c24] rounded-lg">
                    <div className="w-1 h-8 rounded-full flex-shrink-0" style={{ background: layer.color }} />
                    <span className="text-xs text-white">{layer.name}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === 'execution' && (
        <div className="grid grid-cols-[1fr_260px] gap-4 flex-1 min-h-0">
          <div className="space-y-2 overflow-y-auto pr-1">
            {/* Execution header */}
            <div className={`flex items-center gap-3 p-4 rounded-xl border
              ${execStatus === 'running' ? 'border-blue-700/30 bg-blue-900/10' :
                execStatus === 'passed'  ? 'border-green-700/30 bg-green-900/10' :
                execStatus === 'failed'  ? 'border-red-700/30 bg-red-900/10' :
                'border-[rgba(255,255,255,0.07)] bg-[#111318]'}`}
            >
              <div className={`w-3 h-3 rounded-full flex-shrink-0
                ${execStatus === 'running' ? 'bg-blue-400 animate-pulse' :
                  execStatus === 'passed'  ? 'bg-green-400' :
                  execStatus === 'failed'  ? 'bg-red-400' : 'bg-zinc-600'}`}
              />
              <p className="text-sm font-medium text-white flex-1">
                LoginFlow — ValidLogin
                {execStatus === 'passed' && ` ✅ PASSED (${elapsedMs}ms)`}
                {execStatus === 'running' && ' — executando...'}
              </p>
            </div>

            {/* Steps */}
            {execSteps.map((step, i) => (
              <StepRow key={i}
                keyword={step.keyword}
                text={step.text}
                status={step.status}
                duration={step.duration}
              />
            ))}

            {execStatus === 'idle' && (
              <div className="text-center py-12 text-[#4a5568] text-sm">
                Clique em Executar para iniciar
              </div>
            )}
          </div>

          {/* Log panel */}
          <div className="bg-[#0a0c10] border border-[rgba(255,255,255,0.07)] rounded-xl p-4 font-mono text-xs overflow-y-auto">
            <p className="text-[#4a5568] mb-2">[Runtime] LKDF v1.4 pronto.</p>
            {execSteps.map((step, i) => (
              <p key={i} className={
                step.status === 'passed'  ? 'text-green-400' :
                step.status === 'failed'  ? 'text-red-400' :
                step.status === 'running' ? 'text-blue-400' : 'text-[#4a5568]'
              }>
                [{step.status?.toUpperCase()}] {step.keyword} {step.text.slice(0, 40)}
                {step.duration ? ` — ${step.duration}ms` : ''}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
