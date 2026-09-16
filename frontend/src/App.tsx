import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  startParseUrl, pollParseUrl, ingestParsed, chatConversation, getToken, setToken,
  startHealthCheck, pollHealthCheck,
  listDocs, updateDoc, deleteDoc, listChanges,
  listCorrections, resolveCorrection,
  type Fragment, type ChatSource, type ChatMessage, type HealthReport,
  type DocItem, type ChangeItem, type CorrectionItem,
} from './api'

const DOMAINS = ['airline', 'credit_card', 'hotel', 'other']
const DOMAIN_LABEL: Record<string, string> = {
  airline: '航司', credit_card: '信用卡', hotel: '酒店', other: '其他',
}
const DOMAIN_COLOR: Record<string, string> = {
  airline: 'bg-sky-500/20 text-sky-300 border-sky-500/40',
  credit_card: 'bg-violet-500/20 text-violet-300 border-violet-500/40',
  hotel: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
  other: 'bg-slate-500/20 text-slate-300 border-slate-500/40',
}

interface Row extends Fragment { checked: boolean }

// 判断这次回车是否应该触发发送：排除输入法组字状态。
// 双重保险：isComposing（标准）+ keyCode===229（组字中浏览器统一上报的键码），
// 两者任一为真都说明用户还在拼字/选词，回车只用于确认候选，不发送。
function isSubmitEnter(e: React.KeyboardEvent): boolean {
  if (e.key !== 'Enter') return false
  if (e.nativeEvent.isComposing) return false
  if (e.keyCode === 229) return false
  return true
}

// 文章发布超过 12 个月视为「可能过时」，来源日期标黄提醒
function isStale(date: string): boolean {
  const t = Date.parse(date)
  if (isNaN(t)) return false
  return Date.now() - t > 365 * 24 * 3600 * 1000
}

// 修复中文场景下 **加粗** 边界失效：CommonMark 规定「闭合 ** 后不能紧跟字/数字、
// 开启 ** 前不能紧贴字/数字」，而中文常写成「约**6分钟**返现」导致加粗不生效、星号外露。
// 办法：把每对 **…** 的【外侧】补空格（开标记左边、闭标记右边），内侧绝不动。
function fixMarkdownBold(text: string): string {
  return text.replace(/\*\*(.+?)\*\*/g, (_m, inner) => ` **${inner}** `)
    .replace(/ {2,}/g, ' ')  // 合并可能产生的多余空格
}

export default function App() {
  const [token, setTok] = useState(getToken())
  const [url, setUrl] = useState('')
  const [title, setTitle] = useState('')
  const [rows, setRows] = useState<Row[]>([])
  const [rawText, setRawText] = useState('')
  const [showRaw, setShowRaw] = useState(false)
  const [loading, setLoading] = useState(false)
  const [parseProgress, setParseProgress] = useState('')
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  const [question, setQuestion] = useState('')
  const [turns, setTurns] = useState<{ msg: ChatMessage; sources?: ChatSource[] }[]>([])
  const [asking, setAsking] = useState(false)

  function saveToken(t: string) { setTok(t); setToken(t) }

  async function handleParse() {
    if (!token) { setMsg({ type: 'err', text: '请先填入 ADMIN_TOKEN' }); return }
    if (!url.trim()) return
    setLoading(true); setMsg(null); setRows([]); setTitle(''); setRawText(''); setShowRaw(false)
    setParseProgress('启动中…')
    try {
      const { task_id } = await startParseUrl(url.trim())
      const t0 = Date.now()
      for (;;) {
        await new Promise(r => setTimeout(r, 2000))
        const t = await pollParseUrl(task_id)
        const secs = Math.floor((Date.now() - t0) / 1000)
        setParseProgress(`${t.progress}（${secs}s）`)
        if (t.status === 'done' && t.result) {
          const d = t.result
          setTitle(d.title || '(无标题)')
          setRawText(d.raw_text || '')
          setRows(d.fragments.map(f => ({ ...f, checked: true })))
          if (d.fragments.length === 0) setMsg({ type: 'err', text: '未解析出与常旅客相关的片段' })
          break
        }
        if (t.status === 'error') {
          setMsg({ type: 'err', text: t.error || '解析失败' })
          break
        }
      }
    } catch (e) {
      setMsg({ type: 'err', text: (e as Error).message })
    } finally { setLoading(false); setParseProgress('') }
  }

  function update(i: number, patch: Partial<Row>) {
    setRows(rs => rs.map((r, j) => j === i ? { ...r, ...patch } : r))
  }

  async function handleIngest() {
    const chosen = rows.filter(r => r.checked)
    if (chosen.length === 0) { setMsg({ type: 'err', text: '没有勾选任何片段' }); return }
    setLoading(true); setMsg(null)
    try {
      const d = await ingestParsed(chosen.map(({ checked, duplicate, ...f }) => { void checked; void duplicate; return f }))
      setMsg({ type: 'ok', text: `成功入库 ${d.added} 段，当前库共 ${d.total} 段` })
      setRows([]); setTitle(''); setRawText(''); setShowRaw(false)
    } catch (e) {
      setMsg({ type: 'err', text: (e as Error).message })
    } finally { setLoading(false) }
  }

  async function handleAsk() {
    if (!question.trim() || asking) return
    const userMsg: ChatMessage = { role: 'user', content: question.trim() }
    const nextTurns = [...turns, { msg: userMsg }]
    setTurns(nextTurns)
    setQuestion('')
    setAsking(true)
    try {
      const history: ChatMessage[] = nextTurns.map(t => t.msg)
      const d = await chatConversation(history)
      setTurns(ts => [...ts, { msg: { role: 'assistant', content: d.answer }, sources: d.sources }])
    } catch (e) {
      setTurns(ts => [...ts, { msg: { role: 'assistant', content: '出错：' + (e as Error).message } }])
    } finally { setAsking(false) }
  }

  function resetChat() { setTurns([]); setQuestion('') }

  // ---- 知识库体检 ----
  const [hcRunning, setHcRunning] = useState(false)
  const [hcProgress, setHcProgress] = useState('')
  const [hcReport, setHcReport] = useState<HealthReport | null>(null)

  async function runHealthCheck() {
    if (hcRunning) return
    setHcRunning(true); setHcReport(null); setHcProgress('启动中…')
    try {
      const { task_id } = await startHealthCheck()
      // 轮询直到完成
      for (;;) {
        await new Promise(r => setTimeout(r, 3000))
        const t = await pollHealthCheck(task_id)
        setHcProgress(t.progress)
        if (t.status === 'done') { setHcReport(t.report); break }
        if (t.status === 'error') { setHcProgress('出错：' + (t.error || '未知')); break }
      }
    } catch (e) {
      setHcProgress('出错：' + (e as Error).message)
    } finally { setHcRunning(false) }
  }

  // ---- 知识管理 ----
  const [showManage, setShowManage] = useState(false)
  const [docs, setDocs] = useState<DocItem[]>([])
  const [changes, setChanges] = useState<ChangeItem[]>([])
  const [editing, setEditing] = useState<Record<string, string>>({})
  const [mgLoading, setMgLoading] = useState(false)

  async function loadManage() {
    setMgLoading(true)
    try {
      const [d, c] = await Promise.all([listDocs(), listChanges()])
      setDocs(d.docs); setChanges(c.changes)
    } catch (e) {
      setMsg({ type: 'err', text: '加载失败：' + (e as Error).message })
    } finally { setMgLoading(false) }
  }

  async function toggleManage() {
    const next = !showManage
    setShowManage(next)
    if (next && docs.length === 0) await loadManage()
  }

  async function saveDoc(id: string) {
    const text = editing[id]
    if (text === undefined) return
    try {
      await updateDoc(id, text)
      setMsg({ type: 'ok', text: '已保存修改' })
      setEditing(e => { const n = { ...e }; delete n[id]; return n })
      await loadManage()
    } catch (e) { setMsg({ type: 'err', text: '保存失败：' + (e as Error).message }) }
  }

  async function removeDoc(id: string) {
    try {
      await deleteDoc(id)
      setMsg({ type: 'ok', text: '已删除' })
      await loadManage()
    } catch (e) { setMsg({ type: 'err', text: '删除失败：' + (e as Error).message }) }
  }

  // ---- 纠错队列 ----
  const [showCorr, setShowCorr] = useState(false)
  const [corrStatus, setCorrStatus] = useState<'pending' | 'all'>('pending')
  const [corrections, setCorrections] = useState<CorrectionItem[]>([])
  const [corrOpen, setCorrOpen] = useState<Record<number, boolean>>({})
  const [corrEdit, setCorrEdit] = useState<Record<string, string>>({})  // doc_id -> 编辑中的正文
  const [corrNote, setCorrNote] = useState<Record<number, string>>({})  // 处理备注

  async function loadCorrections(status = corrStatus) {
    try {
      const r = await listCorrections(status)
      setCorrections(r.corrections)
    } catch (e) { setMsg({ type: 'err', text: '加载纠错失败：' + (e as Error).message }) }
  }

  async function toggleCorr() {
    const next = !showCorr
    setShowCorr(next)
    if (next) await loadCorrections()
  }

  async function switchCorrStatus(s: 'pending' | 'all') {
    setCorrStatus(s)
    await loadCorrections(s)
  }

  // 纠错卡片内就地保存关联知识：复用知识管理的 updateDoc，改完两处列表都刷新
  async function saveCorrDoc(docId: string) {
    const text = corrEdit[docId]
    if (text === undefined) return
    try {
      await updateDoc(docId, text)
      setMsg({ type: 'ok', text: '已保存修改' })
      setCorrEdit(e => { const n = { ...e }; delete n[docId]; return n })
      await loadCorrections()
      if (showManage) await loadManage()
    } catch (e) { setMsg({ type: 'err', text: '保存失败：' + (e as Error).message }) }
  }

  async function markResolved(id: number) {
    try {
      await resolveCorrection(id, corrNote[id] || '')
      setMsg({ type: 'ok', text: '已标记处理' })
      setCorrNote(n => { const x = { ...n }; delete x[id]; return x })
      await loadCorrections()
    } catch (e) { setMsg({ type: 'err', text: '标记失败：' + (e as Error).message }) }
  }

  const pendingCount = corrections.filter(c => c.status === 'pending').length

  // 来源按 url 去重
  function uniqSources(sources: ChatSource[]) {
    const seen = new Set<string>()
    const out: ChatSource[] = []
    for (const s of sources) {
      const key = s.url || 's:' + s.source
      if (seen.has(key)) continue
      seen.add(key); out.push(s)
    }
    return out
  }

  const checkedCount = rows.filter(r => r.checked).length

  return (
    <div className="min-h-full bg-gradient-to-br from-[#0b1020] via-[#0d1226] to-[#131a35] text-slate-100">
      <div className="mx-auto max-w-3xl px-5 py-10">
        <motion.div
          initial={{ opacity: 0, y: -12 }} animate={{ opacity: 1, y: 0 }}
          className="mb-8"
        >
          <h1 className="text-2xl font-bold tracking-tight bg-gradient-to-r from-sky-300 to-violet-300 bg-clip-text text-transparent">
            ffp-rag 管理后台
          </h1>
          <p className="text-sm text-slate-400 mt-1">常旅客知识库 · 传 URL → 审核片段 → 入库</p>
        </motion.div>

        <Card>
          <div className="flex items-center justify-between">
            <div className="text-xs text-slate-400">知识库体检 · 时效性 / 覆盖盲区 / 矛盾冲突</div>
            <button
              onClick={runHealthCheck} disabled={hcRunning}
              className="rounded-lg px-4 py-1.5 text-sm font-medium bg-teal-500 hover:bg-teal-400 disabled:opacity-50 transition shadow-lg shadow-teal-500/20"
            >
              {hcRunning ? '体检中…' : '开始体检'}
            </button>
          </div>
          {hcRunning && (
            <div className="mt-2 text-xs text-teal-300">{hcProgress}</div>
          )}
          {hcReport && (
            <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="mt-3 space-y-3">
              <div className="flex gap-3 text-xs">
                <span className="rounded-full bg-slate-700/50 px-2.5 py-1">共 {hcReport.total_docs} 条知识</span>
                <span className="rounded-full bg-amber-500/15 text-amber-300 px-2.5 py-1">过期 {hcReport.summary.stale_count}</span>
                <span className="rounded-full bg-sky-500/15 text-sky-300 px-2.5 py-1">盲区 {hcReport.summary.gap_count}</span>
                <span className="rounded-full bg-rose-500/15 text-rose-300 px-2.5 py-1">矛盾 {hcReport.summary.conflict_count}</span>
              </div>

              {hcReport.timeliness.length > 0 && (
                <div>
                  <div className="text-xs font-medium text-amber-300 mb-1">⏰ 需复核（可能过期）</div>
                  <ul className="space-y-1">
                    {hcReport.timeliness.map((f, i) => (
                      <li key={i} className="text-xs text-slate-300 rounded-md bg-amber-500/10 border border-amber-500/30 px-2.5 py-1.5">
                        <span className="text-amber-400">{f.months}月前</span> · {f.reason}
                        <div className="text-slate-400 mt-0.5">{f.text}…</div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {hcReport.completeness.gaps.length > 0 && (
                <div>
                  <div className="text-xs font-medium text-sky-300 mb-1">
                    🕳 覆盖盲区（用户可能会问，但库里缺）· 基线 {hcReport.completeness.total_questions} 题
                  </div>
                  <ul className="flex flex-wrap gap-1.5">
                    {hcReport.completeness.gaps.map((g, i) => (
                      <li key={i} className="text-xs text-sky-200 rounded-full bg-sky-500/10 border border-sky-500/30 px-2.5 py-1">
                        {g.question}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {hcReport.consistency.length > 0 && (
                <div>
                  <div className="text-xs font-medium text-rose-300 mb-1">⚔ 矛盾冲突</div>
                  <ul className="space-y-1.5">
                    {hcReport.consistency.map((c, i) => (
                      <li key={i} className="text-xs rounded-md bg-rose-500/10 border border-rose-500/30 px-2.5 py-1.5">
                        <div className="text-rose-300">{c.reason}</div>
                        <div className="text-slate-400 mt-0.5">A（{c.a_source}）：{c.a}…</div>
                        <div className="text-slate-400">B（{c.b_source}）：{c.b}…</div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {hcReport.summary.stale_count === 0 && hcReport.summary.gap_count === 0 && hcReport.summary.conflict_count === 0 && (
                <div className="text-xs text-emerald-300">✓ 未发现问题，知识库很健康</div>
              )}
            </motion.div>
          )}
        </Card>

        <Card>
          <div className="flex items-center justify-between">
            <div className="text-xs text-slate-400">
              纠错队列 · 用户报错 → 修正知识
              {showCorr && pendingCount > 0 && (
                <span className="ml-2 rounded-full bg-rose-500/20 text-rose-300 px-2 py-0.5">
                  {pendingCount} 待处理
                </span>
              )}
            </div>
            <button
              onClick={toggleCorr}
              className="rounded-lg px-4 py-1.5 text-sm font-medium bg-slate-600 hover:bg-slate-500 transition"
            >
              {showCorr ? '收起' : '打开'}
            </button>
          </div>

          {showCorr && (
            <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="mt-3 space-y-3">
              <div className="flex gap-2 text-xs">
                {(['pending', 'all'] as const).map(s => (
                  <button
                    key={s} onClick={() => switchCorrStatus(s)}
                    className={`rounded-full px-2.5 py-1 transition ${corrStatus === s
                      ? 'bg-sky-500/20 text-sky-300 border border-sky-500/40'
                      : 'bg-slate-700/40 text-slate-400 hover:text-slate-300'}`}
                  >
                    {s === 'pending' ? '待处理' : '全部'}
                  </button>
                ))}
              </div>

              {corrections.length === 0 && (
                <div className="text-xs text-emerald-300">✓ 没有待处理的报错</div>
              )}

              <ul className="space-y-2">
                {corrections.map(c => (
                  <li key={c.id} className="rounded-lg bg-slate-800/60 border border-slate-700/60 px-3 py-2">
                    <div
                      className="cursor-pointer"
                      onClick={() => setCorrOpen(o => ({ ...o, [c.id]: !o[c.id] }))}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="text-xs text-slate-200">{c.question}</div>
                        <div className="shrink-0 text-[10px] text-slate-500">{c.created_at}</div>
                      </div>
                      {c.note
                        ? <div className="mt-1 text-xs text-rose-300">用户说：{c.note}</div>
                        : <div className="mt-1 text-xs text-slate-500">（用户未填说明）</div>}
                      {c.status === 'done' && (
                        <div className="mt-1 text-xs text-emerald-400">
                          ✓ 已处理{c.resolution ? '：' + c.resolution : ''}
                        </div>
                      )}
                    </div>

                    {corrOpen[c.id] && (
                      <div className="mt-2 space-y-2 border-t border-slate-700/60 pt-2">
                        {c.rewritten && c.rewritten !== c.question && (
                          <div className="text-[11px] text-slate-500">检索问题：{c.rewritten}</div>
                        )}
                        <div className="text-xs text-slate-400 whitespace-pre-wrap max-h-40 overflow-y-auto rounded-md bg-slate-900/60 px-2 py-1.5">
                          {c.answer || '（无回答快照）'}
                        </div>

                        {c.docs.length === 0 ? (
                          <div className="text-xs text-amber-300 rounded-md bg-amber-500/10 border border-amber-500/30 px-2.5 py-1.5">
                            无关联知识（可能是库里缺这条）—— 考虑走上面的 URL 摄入补录
                          </div>
                        ) : (
                          <div className="space-y-2">
                            <div className="text-[11px] font-medium text-slate-400">命中的知识（可就地修改）</div>
                            {c.docs.map(d => d.missing ? (
                              <div key={d.id} className="text-xs text-slate-500 italic">
                                {d.id} —— 已被删除
                              </div>
                            ) : (
                              <div key={d.id} className="rounded-md bg-slate-900/60 px-2 py-1.5">
                                <textarea
                                  value={corrEdit[d.id] !== undefined ? corrEdit[d.id] : d.text}
                                  onChange={e => setCorrEdit(s => ({ ...s, [d.id]: e.target.value }))}
                                  rows={3}
                                  className="w-full bg-transparent text-xs text-slate-300 outline-none resize-y"
                                />
                                <div className="flex items-center gap-3 mt-1">
                                  <span className="text-[10px] text-slate-500">{d.meta?.source}</span>
                                  {corrEdit[d.id] !== undefined && (
                                    <>
                                      <button onClick={() => saveCorrDoc(d.id)} className="text-xs text-emerald-400 hover:text-emerald-300">保存</button>
                                      <button
                                        onClick={() => setCorrEdit(s => { const n = { ...s }; delete n[d.id]; return n })}
                                        className="text-xs text-slate-500 hover:text-slate-400"
                                      >取消</button>
                                    </>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}

                        {c.status === 'pending' && (
                          <div className="flex gap-2">
                            <input
                              value={corrNote[c.id] || ''}
                              onChange={e => setCorrNote(n => ({ ...n, [c.id]: e.target.value }))}
                              placeholder="处理备注：改了什么 / 为什么不用改"
                              className="flex-1 rounded-md bg-slate-900/60 border border-slate-700 px-2 py-1 text-xs outline-none focus:border-sky-500"
                            />
                            <button
                              onClick={() => markResolved(c.id)}
                              className="rounded-md px-3 py-1 text-xs font-medium bg-emerald-600 hover:bg-emerald-500 transition"
                            >
                              标记已处理
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </motion.div>
          )}
        </Card>

        <Card>
          <div className="flex items-center justify-between">
            <div className="text-xs text-slate-400">知识管理 · 编辑 / 删除 / 变更记录</div>
            <button
              onClick={toggleManage}
              className="rounded-lg px-4 py-1.5 text-sm font-medium bg-slate-600 hover:bg-slate-500 transition"
            >
              {showManage ? '收起' : '打开'}
            </button>
          </div>

          {showManage && (
            <div className="mt-3 space-y-4">
              {mgLoading && <div className="text-xs text-slate-400">加载中…</div>}

              {/* 变更流水 */}
              {changes.length > 0 && (
                <div>
                  <div className="text-xs font-medium text-slate-300 mb-1">变更记录</div>
                  <ul className="space-y-1 max-h-40 overflow-auto">
                    {changes.map((c, i) => (
                      <li key={i} className="text-xs text-slate-400 flex gap-2">
                        <span className={
                          c.action === 'add' ? 'text-emerald-400' :
                          c.action === 'update' ? 'text-sky-400' : 'text-rose-400'}>
                          {c.action === 'add' ? '＋' : c.action === 'update' ? '✎' : '✕'}
                        </span>
                        <span className="text-slate-500">{c.at.slice(5, 16).replace('T', ' ')}</span>
                        <span className="flex-1">{c.summary}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* 知识列表 */}
              <div>
                <div className="text-xs font-medium text-slate-300 mb-1">库中知识（{docs.length} 条）</div>
                <div className="space-y-2 max-h-96 overflow-auto">
                  {docs.map(d => {
                    const isEditing = editing[d.id] !== undefined
                    return (
                      <div key={d.id} className="rounded-lg bg-slate-900/60 border border-slate-700 p-2.5">
                        <div className="flex items-center gap-2 mb-1 text-xs">
                          <span className="rounded bg-slate-700/50 px-1.5 py-0.5 text-slate-300">{d.domain}</span>
                          {d.subtopic && <span className="rounded bg-teal-500/15 text-teal-300 px-1.5 py-0.5">{d.subtopic}</span>}
                          <span className="text-slate-500 truncate flex-1">{d.source}{d.date ? ` · ${d.date}` : ''}</span>
                        </div>
                        {isEditing ? (
                          <textarea
                            value={editing[d.id]} onChange={e => setEditing(ed => ({ ...ed, [d.id]: e.target.value }))}
                            rows={3}
                            className="w-full rounded-md bg-slate-900 border border-sky-500/50 px-2 py-1.5 text-xs leading-relaxed outline-none resize-y"
                          />
                        ) : (
                          <div className="text-xs text-slate-300 leading-relaxed">{d.text}</div>
                        )}
                        <div className="flex gap-2 mt-1.5">
                          {isEditing ? (
                            <>
                              <button onClick={() => saveDoc(d.id)} className="text-xs text-emerald-400 hover:text-emerald-300">保存</button>
                              <button onClick={() => setEditing(e => { const n = { ...e }; delete n[d.id]; return n })} className="text-xs text-slate-500 hover:text-slate-400">取消</button>
                            </>
                          ) : (
                            <>
                              <button onClick={() => setEditing(e => ({ ...e, [d.id]: d.text }))} className="text-xs text-sky-400 hover:text-sky-300">编辑</button>
                              <button onClick={() => removeDoc(d.id)} className="text-xs text-rose-400 hover:text-rose-300">删除</button>
                            </>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          )}
        </Card>

        <Card>
          <label className="text-xs text-slate-400">ADMIN_TOKEN</label>
          <input
            type="password" value={token} onChange={e => saveToken(e.target.value)}
            placeholder="粘贴管理员令牌（保存在本地浏览器）"
            className="mt-1 w-full rounded-lg bg-slate-900/70 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-sky-500 transition"
          />
        </Card>

        <Card>
          <div className="flex gap-2">
            <input
              value={url} onChange={e => setUrl(e.target.value)}
              onKeyDown={e => { if (isSubmitEnter(e)) { e.preventDefault(); handleParse() } }}
              placeholder="粘贴文章 URL（公众号图文 / 普通网页；小红书不支持）"
              className="flex-1 rounded-lg bg-slate-900/70 border border-slate-700 px-3 py-2.5 text-sm outline-none focus:border-sky-500 transition"
            />
            <button
              onClick={handleParse} disabled={loading}
              className="rounded-lg px-5 py-2.5 text-sm font-medium bg-sky-500 hover:bg-sky-400 disabled:opacity-50 transition shadow-lg shadow-sky-500/20"
            >
              {loading ? '解析中…' : '解析'}
            </button>
          </div>
          {loading && parseProgress && (
            <div className="mt-2 flex items-center gap-2 text-xs text-sky-300">
              <span className="inline-block h-3 w-3 rounded-full border-2 border-sky-400 border-t-transparent animate-spin" />
              {parseProgress}
            </div>
          )}
        </Card>

        <AnimatePresence>
          {msg && (
            <motion.div
              initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className={`mb-4 rounded-lg px-4 py-2.5 text-sm border ${
                msg.type === 'ok'
                  ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40'
                  : 'bg-rose-500/15 text-rose-300 border-rose-500/40'}`}
            >
              {msg.text}
            </motion.div>
          )}
        </AnimatePresence>

        <AnimatePresence>
          {rows.length > 0 && (
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="mb-4"
            >
              <div className="flex items-center justify-between mb-3">
                <div className="text-sm text-slate-300">
                  <span className="text-slate-500">来源：</span>{title}
                  <span className="ml-2 text-slate-500">共 {rows.length} 段，选中 {checkedCount}</span>
                </div>
                <button
                  onClick={handleIngest} disabled={loading || checkedCount === 0}
                  className="rounded-lg px-4 py-2 text-sm font-medium bg-emerald-500 hover:bg-emerald-400 disabled:opacity-40 transition shadow-lg shadow-emerald-500/20"
                >
                  入库选中项
                </button>
              </div>

              {rawText && (
                <div className="mb-3">
                  <button
                    onClick={() => setShowRaw(v => !v)}
                    className="text-xs text-sky-400 hover:text-sky-300 transition"
                  >
                    {showRaw ? '▲ 收起原文' : '▼ 查看抓取到的原文（对照 AI 归纳）'}
                  </button>
                  <AnimatePresence>
                    {showRaw && (
                      <motion.pre
                        initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                        className="mt-2 max-h-72 overflow-auto rounded-lg bg-slate-900/70 border border-slate-700 px-3 py-2 text-xs leading-relaxed text-slate-300 whitespace-pre-wrap"
                      >
                        {rawText}
                      </motion.pre>
                    )}
                  </AnimatePresence>
                </div>
              )}

              <div className="space-y-3">
                {rows.map((r, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.04 }}
                    className={`rounded-xl border p-4 transition ${
                      r.checked ? 'bg-slate-800/60 border-slate-600' : 'bg-slate-900/40 border-slate-800 opacity-60'}`}
                  >
                    <div className="flex items-start gap-3">
                      <input
                        type="checkbox" checked={r.checked}
                        onChange={e => update(i, { checked: e.target.checked })}
                        className="mt-1.5 h-4 w-4 accent-emerald-500"
                      />
                      <div className="flex-1 space-y-2">
                        <div className="flex gap-2 items-center">
                          <select
                            value={r.domain} onChange={e => update(i, { domain: e.target.value })}
                            className={`rounded-md border px-2 py-1 text-xs font-medium outline-none ${DOMAIN_COLOR[r.domain] || DOMAIN_COLOR.other}`}
                          >
                            {DOMAINS.map(d => <option key={d} value={d} className="bg-slate-800 text-slate-100">{DOMAIN_LABEL[d]}</option>)}
                          </select>
                          <input
                            value={r.source} onChange={e => update(i, { source: e.target.value })}
                            placeholder="来源标签"
                            className="flex-1 rounded-md bg-slate-900/70 border border-slate-700 px-2 py-1 text-xs outline-none focus:border-sky-500"
                          />
                          <input
                            value={r.subtopic || ''} onChange={e => update(i, { subtopic: e.target.value })}
                            placeholder="细分"
                            className="w-24 rounded-md bg-teal-500/10 border border-teal-500/40 text-teal-300 px-2 py-1 text-xs outline-none focus:border-teal-400"
                          />
                        </div>
                        <textarea
                          value={r.text} onChange={e => update(i, { text: e.target.value })}
                          rows={3}
                          className="w-full rounded-md bg-slate-900/70 border border-slate-700 px-3 py-2 text-sm leading-relaxed outline-none focus:border-sky-500 resize-y"
                        />
                        {r.duplicate && (
                          <div className="mt-2 rounded-md bg-amber-500/10 border border-amber-500/40 px-3 py-2 text-xs text-amber-300">
                            ⚠ 与已有内容相似（{(r.duplicate.score * 100).toFixed(0)}%）
                            <span className="text-amber-400/70">
                              ，来自「{r.duplicate.source}」{r.duplicate.date ? ` · ${r.duplicate.date}` : ''}
                            </span>
                            <div className="mt-1 text-amber-200/60 leading-snug">
                              库中原文：{r.duplicate.text.slice(0, 80)}…
                            </div>
                            <div className="mt-1 text-amber-400/60">
                              若是重复可取消勾选；若内容有更新（如比例变了）则保留。
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </motion.div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <Card>
          <div className="flex items-center justify-between mb-3">
            <div className="text-xs text-slate-400">问答（可连续追问，如「那云闪付呢？」）</div>
            {turns.length > 0 && (
              <button onClick={resetChat} className="text-xs text-slate-500 hover:text-slate-300 transition">
                清空对话
              </button>
            )}
          </div>

          {turns.length > 0 && (
            <div className="mb-3 space-y-3 max-h-[28rem] overflow-auto pr-1">
              {turns.map((t, i) => t.msg.role === 'user' ? (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-violet-500/20 border border-violet-500/40 px-3.5 py-2 text-sm text-violet-100">
                    {t.msg.content}
                  </div>
                </div>
              ) : (
                <motion.div
                  key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                  className="flex justify-start"
                >
                  <div className="max-w-[90%] rounded-2xl rounded-bl-sm bg-slate-900/70 border border-slate-700 px-4 py-3 text-[15px] leading-7 text-slate-100">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                        ul: ({ children }) => <ul className="my-2 space-y-1.5 list-none">{children}</ul>,
                        li: ({ children }) => (
                          <li className="flex gap-2">
                            <span className="text-sky-400 mt-0.5">•</span>
                            <span className="flex-1">{children}</span>
                          </li>
                        ),
                        strong: ({ children }) => <strong className="font-semibold text-sky-300">{children}</strong>,
                        a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer" className="text-sky-400 underline">{children}</a>,
                      }}
                    >
                      {fixMarkdownBold(t.msg.content)}
                    </ReactMarkdown>
                    {t.sources && uniqSources(t.sources).length > 0 && (
                      <div className="mt-2.5 pt-2.5 border-t border-slate-700/60 flex flex-wrap items-center gap-2">
                        <span className="text-xs text-slate-500">来源：</span>
                        {uniqSources(t.sources).map((s, j) => s.url ? (
                          <a key={j} href={s.url} target="_blank" rel="noreferrer"
                            className="inline-flex items-center gap-1 rounded-full bg-sky-500/15 hover:bg-sky-500/25 text-sky-300 border border-sky-500/40 px-2.5 py-1 text-xs transition">
                            📄 {s.source}
                            {s.date && (
                              <span className={isStale(s.date) ? 'text-amber-400' : 'text-sky-400/60'}>
                                · {s.date}{isStale(s.date) ? ' ⚠︎' : ''}
                              </span>
                            )}
                          </a>
                        ) : (
                          <span key={j} className="inline-flex items-center gap-1 rounded-full bg-slate-700/40 text-slate-400 border border-slate-600 px-2.5 py-1 text-xs">
                            {s.source}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </motion.div>
              ))}
              {asking && (
                <div className="flex justify-start">
                  <div className="rounded-2xl rounded-bl-sm bg-slate-900/70 border border-slate-700 px-3.5 py-2.5 text-sm text-slate-500">
                    思考中…
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="flex gap-2">
            <input
              value={question} onChange={e => setQuestion(e.target.value)}
              onKeyDown={e => { if (isSubmitEnter(e)) { e.preventDefault(); handleAsk() } }}
              placeholder={turns.length ? '继续追问…' : '问一个问题，如：国航金卡有哪些权益？'}
              className="flex-1 rounded-lg bg-slate-900/70 border border-slate-700 px-3 py-2.5 text-sm outline-none focus:border-violet-500 transition"
            />
            <button
              onClick={handleAsk} disabled={asking}
              className="rounded-lg px-5 py-2.5 text-sm font-medium bg-violet-500 hover:bg-violet-400 disabled:opacity-50 transition shadow-lg shadow-violet-500/20"
            >
              {asking ? '思考中…' : '发送'}
            </button>
          </div>
        </Card>
      </div>
    </div>
  )
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
      className="mb-4 rounded-xl bg-slate-800/40 border border-slate-700/60 backdrop-blur p-4 shadow-xl shadow-black/20"
    >
      {children}
    </motion.div>
  )
}
