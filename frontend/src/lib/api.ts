// frontend/src/lib/api.ts
// AQuA-QE LKDF v1.4 — Typed API Client

import axios, { AxiosInstance } from 'axios'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8080'

export const api: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 60_000,
})

// Attach JWT from localStorage
api.interceptors.request.use((config) => {
  const token = typeof window !== 'undefined'
    ? localStorage.getItem('lkdf_token')
    : null
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Refresh / logout on 401
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401 && typeof window !== 'undefined') {
      localStorage.removeItem('lkdf_token')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  },
)

// ── Types ─────────────────────────────────────────────────────────────────

export interface Story {
  external_id:    string
  title:          string
  description:    string
  status:         string
  current_version: number
  criticality:    'P0' | 'P1' | 'P2'
  created_at:     string
  updated_at:     string
}

export interface Flow {
  id:             string
  name:           string
  requirement_ref: string
  adapter:        string
  priority:       string
  dsl_source:     string
  scenario_count: number
  step_count:     number
  status:         string
  project_id:     string
  created_at:     string
  updated_at:     string
}

export interface Execution {
  id:               string
  execution_id:     string
  flow_name:        string
  requirement_ref:  string
  adapter:          string
  status:           string
  total_scenarios:  number
  passed_scenarios: number
  failed_scenarios: number
  success_rate:     number
  duration_ms:      number
  started_at:       string
  finished_at:      string
}

export interface TraceEntry {
  id:               string
  requirement_id:   string
  flow_name:        string
  scenario_name:    string
  execution_status: string
  coverage_pct:     number
  created_at:       string
}

export interface PolicyReport {
  policy_name:       string
  subject_id:        string
  overall_result:    string
  blocking_failures: number
  warnings:          number
  gates:             Record<string, number>
  failed_gates:      string[]
}

export interface PreventiveSuggestion {
  id:              string
  suggestion_type: string
  title:           string
  description:     string
  rationale:       string
  confidence:      number
  priority:        string
  action_items:    string[]
}

export interface ConformanceReport {
  url:               string
  is_aa_compliant:   boolean
  compliance_pct:    number
  violations_total:  number
  violations_aa:     number
  blocking:          number
}

export interface PageResponse<T> {
  content:       T[]
  page:          number
  size:          number
  totalElements: number
  totalPages:    number
  last:          boolean
}

// ── API methods ───────────────────────────────────────────────────────────

export const flowsApi = {
  list:   (projectId: string, page = 0) =>
    api.get<PageResponse<Flow>>(`/flows?projectId=${projectId}&page=${page}`),
  get:    (id: string) =>
    api.get<Flow>(`/flows/${id}`),
  create: (data: Partial<Flow>) =>
    api.post<Flow>('/flows', data),
  update: (id: string, data: Partial<Flow>) =>
    api.patch<Flow>(`/flows/${id}`, data),
  delete: (id: string) =>
    api.delete(`/flows/${id}`),
  parse:  (id: string) =>
    api.post(`/flows/${id}/parse`),
}

export const executionsApi = {
  trigger: (flowId: string, dryRun = false) =>
    api.post<Execution>('/executions/trigger', { flowId, dryRun }),
  get:     (executionId: string) =>
    api.get<Execution>(`/executions/${executionId}`),
  list:    (flowId: string, page = 0) =>
    api.get<PageResponse<Execution>>(`/executions?flowId=${flowId}&page=${page}`),
}

export const rtmApi = {
  list:          (page = 0) =>
    api.get<PageResponse<TraceEntry>>(`/rtm?page=${page}&size=50`),
  summary:       () =>
    api.get('/rtm/summary'),
  byRequirement: (reqId: string) =>
    api.get<TraceEntry[]>(`/rtm/requirement/${encodeURIComponent(reqId)}`),
}

export const cognitiveApi = {
  analyze:  (requirementText: string, requirementId = 'REQ-AUTO') =>
    api.post('/requirements/analyze', { requirement_text: requirementText, requirement_id: requirementId }),
  pipeline: (requirementText: string, requirementId = 'REQ-AUTO') =>
    api.post('/cognitive/pipeline', { requirement_text: requirementText, requirement_id: requirementId }),
  ambiguity: (requirementText: string) =>
    api.post('/requirements/ambiguity/full', { requirement_text: requirementText }),
  health:    () =>
    api.get('/cognitive/health'),
}

export const policyApi = {
  evaluate: (subjectId: string, ctx: Record<string, unknown>) =>
    api.post<PolicyReport>('/policy/evaluate', { subject_id: subjectId, context: ctx }),
}
