// 极简 API 封装：token 存 localStorage，请求自动带 Authorization。

const TOKEN_KEY = 'ffp_admin_token'

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setToken(t: string) {
  localStorage.setItem(TOKEN_KEY, t)
}

export interface DuplicateInfo {
  score: number
  source: string
  text: string
  date?: string
  url?: string
}

export interface Fragment {
  domain: string
  subtopic?: string
  source: string
  text: string
  url?: string
  date?: string
  duplicate?: DuplicateInfo | null
}

export interface ChatSource {
  domain: string
  source: string
  score: number
  url: string
  date?: string
}

async function post<T>(url: string, body: unknown, auth = false): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (auth) headers['Authorization'] = 'Bearer ' + getToken()
  const res = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body) })
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try {
      const d = await res.json()
      if (d.detail) msg = d.detail
    } catch { /* ignore */ }
    throw new Error(msg)
  }
  return res.json()
}

export interface ParseResult {
  url: string
  title: string
  fragments: Fragment[]
  raw_text: string
}

export interface ParseTask {
  id: string
  status: 'running' | 'done' | 'error'
  progress: string
  result: ParseResult | null
  error: string | null
}

export function startParseUrl(url: string) {
  return post<{ task_id: string }>('/admin/parse-url', { url }, true)
}

export async function pollParseUrl(taskId: string): Promise<ParseTask> {
  const res = await fetch('/admin/parse-url/' + taskId, {
    headers: { Authorization: 'Bearer ' + getToken() },
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export function ingestParsed(fragments: Fragment[]) {
  return post<{ added: number; total: number }>(
    '/admin/ingest-parsed', { fragments }, true,
  )
}

export function chat(question: string) {
  return post<{ answer: string; sources: ChatSource[] }>(
    '/chat', { question },
  )
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export function chatConversation(messages: ChatMessage[]) {
  return post<{ answer: string; sources: ChatSource[]; rewritten: string }>(
    '/chat/conversation', { messages },
  )
}

// ---- 知识库体检 ----

export interface HealthReport {
  total_docs: number
  timeliness: { text: string; source: string; date: string; months: number; reason: string; url: string }[]
  completeness: { total_questions: number; gaps: { question: string; top_score: number }[] }
  consistency: { a: string; a_source: string; b: string; b_source: string; reason: string }[]
  summary: { stale_count: number; gap_count: number; conflict_count: number }
  finished_at: string
}

export interface HealthTask {
  id: string
  status: 'running' | 'done' | 'error'
  progress: string
  report: HealthReport | null
  error: string | null
}

export function startHealthCheck() {
  return post<{ task_id: string }>('/admin/health-check', {}, true)
}

export async function pollHealthCheck(taskId: string): Promise<HealthTask> {
  const res = await fetch('/admin/health-check/' + taskId, {
    headers: { Authorization: 'Bearer ' + getToken() },
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

// ---- 知识管理（CRUD + 变更追踪）----

export interface DocItem {
  id: string
  text: string
  domain: string
  subtopic: string
  source: string
  url: string
  date: string
}

export interface ChangeItem {
  action: string
  target: string
  summary: string
  at: string
}

async function authGet<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { Authorization: 'Bearer ' + getToken() } })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export function listDocs() {
  return authGet<{ docs: DocItem[] }>('/admin/docs')
}

export async function updateDoc(id: string, text: string) {
  const res = await fetch('/admin/docs/' + id, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + getToken() },
    body: JSON.stringify({ text }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function deleteDoc(id: string) {
  const res = await fetch('/admin/docs/' + id, {
    method: 'DELETE',
    headers: { Authorization: 'Bearer ' + getToken() },
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export function listChanges() {
  return authGet<{ changes: ChangeItem[] }>('/admin/changelog')
}
