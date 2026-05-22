// frontend/src/app/settings/page.tsx
'use client'
import { useState } from 'react'
import { Save, Eye, EyeOff } from 'lucide-react'

export default function SettingsPage() {
  const [showKey, setShowKey] = useState(false)
  const [saved, setSaved]     = useState(false)
  const [cfg, setCfg] = useState({
    apiUrl:       'http://localhost:8080',
    anthropicKey: '',
    openaiKey:    '',
    ollamaUrl:    '',
    defaultAdapter: 'playwright',
    defaultBrowser: 'chromium',
    headless:       true,
    wcagLevel:      'AA',
    failFast:       false,
  })

  function save() {
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <p className="text-sm text-[#8892a4] mt-1">Configurações do LKDF Runtime</p>
      </div>

      {[
        {
          title: 'Conexão',
          fields: [
            { label:'API Gateway URL', key:'apiUrl', type:'text', placeholder:'http://localhost:8080' },
          ],
        },
        {
          title: 'AI Providers',
          fields: [
            { label:'Anthropic API Key', key:'anthropicKey', type:'password', placeholder:'sk-ant-...' },
            { label:'OpenAI API Key',    key:'openaiKey',    type:'password', placeholder:'sk-...' },
            { label:'Ollama Base URL',   key:'ollamaUrl',    type:'text',     placeholder:'http://localhost:11434' },
          ],
        },
        {
          title: 'Adapter Defaults',
          fields: [
            { label:'Default Adapter', key:'defaultAdapter', type:'select', options:['playwright','selenium','cypress','api','robot-framework'] },
            { label:'Default Browser', key:'defaultBrowser', type:'select', options:['chromium','firefox','webkit'] },
          ],
        },
        {
          title: 'Quality Policy',
          fields: [
            { label:'WCAG Target Level', key:'wcagLevel', type:'select', options:['A','AA','AAA'] },
          ],
        },
      ].map(section => (
        <div key={section.title} className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-5 space-y-4">
          <p className="text-sm font-semibold text-white">{section.title}</p>
          {section.fields.map(field => (
            <div key={field.key}>
              <label className="block text-xs text-[#8892a4] mb-1.5">{field.label}</label>
              {field.type === 'select' ? (
                <select value={(cfg as any)[field.key]}
                  onChange={e => setCfg(c => ({...c, [field.key]: e.target.value}))}
                  className="w-full px-3 py-2 bg-[#181c24] border border-[rgba(255,255,255,0.07)] rounded-lg text-sm text-white focus:outline-none focus:border-[#4f7cff]">
                  {field.options?.map(o => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <div className="relative">
                  <input
                    type={field.type === 'password' && !showKey ? 'password' : 'text'}
                    value={(cfg as any)[field.key]}
                    onChange={e => setCfg(c => ({...c, [field.key]: e.target.value}))}
                    placeholder={field.placeholder}
                    className="w-full px-3 py-2 bg-[#181c24] border border-[rgba(255,255,255,0.07)] rounded-lg text-sm text-white placeholder-[#4a5568] focus:outline-none focus:border-[#4f7cff]"
                  />
                  {field.type === 'password' && (
                    <button onClick={() => setShowKey(s => !s)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-[#4a5568] hover:text-white">
                      {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      ))}

      {/* Toggles */}
      <div className="bg-[#111318] border border-[rgba(255,255,255,0.07)] rounded-xl p-5 space-y-4">
        <p className="text-sm font-semibold text-white">Comportamento</p>
        {[
          { label:'Headless mode',    key:'headless',  desc:'Executar browsers sem interface gráfica' },
          { label:'Fail Fast',        key:'failFast',  desc:'Parar pipeline no primeiro gate que falhar' },
        ].map(t => (
          <div key={t.key} className="flex items-center justify-between">
            <div>
              <p className="text-sm text-white">{t.label}</p>
              <p className="text-xs text-[#8892a4]">{t.desc}</p>
            </div>
            <button onClick={() => setCfg(c => ({...c, [t.key]: !(c as any)[t.key]}))}
              className={`w-11 h-6 rounded-full transition-colors relative ${(cfg as any)[t.key] ? 'bg-[#4f7cff]' : 'bg-[#181c24] border border-[rgba(255,255,255,0.1)]'}`}>
              <div className={`w-4 h-4 rounded-full bg-white absolute top-1 transition-all ${(cfg as any)[t.key] ? 'left-6' : 'left-1'}`} />
            </button>
          </div>
        ))}
      </div>

      <button onClick={save}
        className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-all
          ${saved ? 'bg-green-600 text-white' : 'bg-[#4f7cff] hover:bg-[#3d6be0] text-white'}`}>
        <Save className="w-4 h-4" />
        {saved ? 'Salvo!' : 'Salvar configurações'}
      </button>
    </div>
  )
}
