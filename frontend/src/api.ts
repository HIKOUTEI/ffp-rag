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
  doc_id?: string
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

// ---- 纠错队列 ----

export interface CorrectionDoc {
  id: string
  text: string
  meta?: Record<string, string>
  missing?: boolean
}

export interface CorrectionItem {
  id: number
  question: string
  rewritten: string
  answer: string
  doc_ids: string[]
  sources: ChatSource[]
  note: string
  openid: string
  status: 'pending' | 'done'
  resolution: string
  created_at: string
  resolved_at: string
  docs: CorrectionDoc[]   // doc_ids 回填出的当前知识正文
}

export function listCorrections(status: 'pending' | 'all' = 'pending') {
  return authGet<{ corrections: CorrectionItem[] }>('/admin/corrections?status=' + status)
}

export async function resolveCorrection(id: number, resolution: string) {
  const res = await fetch('/admin/corrections/' + id, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + getToken() },
    body: JSON.stringify({ resolution }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

// ---- 奖赏钱规则集 ----
// 以下 interface 手抄自 backend/app/rewardcash/schemas.py，没有代码生成也没有校验：
// 后端改字段这边不报错，只会在运行时拿到 undefined。改任一侧都要对着另一侧核一遍。

export type CapPeriod = 'calendar_year' | 'calendar_month' | 'promo_period' | 'membership_year'
export type CapKind = 'spend' | 'reward'
export type RuleKind = 'rate' | 'flat'
export type Recurrence = 'recurring' | 'one_off'
export type Confidence = 'official' | 'user_verified' | 'unverified' | 'unavailable'
export type Region = 'mainland' | 'macau' | 'hongkong' | 'overseas'
export type MerchantCategory = 'dining' | 'other'
export type Channel = 'rewardplus_qr' | 'unionpay_qr' | 'mobile_pay' | 'physical_card'
  | 'alipayhk' | 'wechat' | 'online' | 'other'

export interface RewardCategory {
  key: string
  name: string
  kind: RuleKind
}

export interface Cap {
  kind: CapKind
  amount: number
  period: CapPeriod
}

export interface ThresholdScope {
  region?: Region | null
}

export interface Threshold {
  amount_hkd: number
  period: CapPeriod
  scope?: ThresholdScope
}

export interface Conditions {
  region?: Region[] | null
  merchant_category?: MerchantCategory[] | null
  channel?: Channel[] | null
  settled_hkd?: boolean | null
}

export interface RuleSource {
  url?: string | null
  clause?: string | null
  checked_at?: string | null
}

export interface Rule {
  id: string
  name: string
  kind: RuleKind
  rate?: number | null          // kind=rate 时必填
  flat_amount?: number | null   // kind=flat 时必填
  recurrence: Recurrence
  reward_category?: string | null   // null = 未知，不参与上限反推
  caps?: Cap[]
  threshold?: Threshold | null
  requires_enrolment?: boolean
  conditions?: Conditions
  period_start?: string | null      // YYYY-MM-DD
  period_end?: string | null
  status: Confidence
  source?: RuleSource
  note?: string | null
}

export interface RuleSet {
  categories: RewardCategory[]
  rules: Rule[]
}

export interface RuleVersion {
  version: number
  updated_at: string
  note: string | null
}

// 规则集接口的 4xx 必须把 detail 原样抛出：422 的 detail 是
// 「规则集校验不通过：<pydantic 完整报错>」，里面的字段路径是定位问题的唯一线索。
async function throwWithDetail(res: Response): Promise<never> {
  let msg = `HTTP ${res.status}`
  try {
    const d = await res.json()
    if (d.detail) msg = d.detail
  } catch { /* ignore */ }
  throw new Error(msg)
}

export async function getAdminRules(version?: number) {
  const url = '/rewardcash/admin/rules' + (version === undefined ? '' : '?version=' + version)
  const res = await fetch(url, { headers: { Authorization: 'Bearer ' + getToken() } })
  if (!res.ok) await throwWithDetail(res)
  return res.json() as Promise<{ version: number; ruleset: RuleSet }>
}

export async function putAdminRules(data: RuleSet, note: string) {
  const res = await fetch('/rewardcash/admin/rules', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + getToken() },
    body: JSON.stringify({ data, note }),
  })
  if (!res.ok) await throwWithDetail(res)
  return res.json() as Promise<{ version: number }>
}

export async function listRuleVersions(limit = 50) {
  const res = await fetch('/rewardcash/admin/rules/versions?limit=' + limit, {
    headers: { Authorization: 'Bearer ' + getToken() },
  })
  if (!res.ok) await throwWithDetail(res)
  return res.json() as Promise<{ versions: RuleVersion[] }>
}
