// 控制台入口：状态容器 + 分区路由。
//
// 所有 useState 和 handler 都留在这里，分区组件是纯展示（props 进、回调出）。
// 这样切区时 React 不会卸载状态——解析到一半去看纠错队列，回来片段还在。
import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  startParseUrl, pollParseUrl, ingestParsed, chatConversation, getToken, setToken,
  startHealthCheck, pollHealthCheck,
  listDocs, updateDoc, deleteDoc, listChanges,
  listCorrections, resolveCorrection,
  getAdminRules, putAdminRules, listRuleVersions,
  type ChatSource, type ChatMessage, type HealthReport,
  type DocItem, type ChangeItem, type CorrectionItem,
  type RuleSet, type RuleVersion,
} from './api'
import { Shell } from './layout/Shell'
import type { SectionId } from './theme'
import { Workbench, type Row } from './sections/Workbench'
import { Health } from './sections/Health'
import { Corrections } from './sections/Corrections'
import { Manage } from './sections/Manage'
import { Rules } from './sections/Rules'

export default function App() {
  const [section, setSection] = useState<SectionId>('workbench')

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
  // manageLoaded 是原来 showManage 的遗产：展开/收起的语义随分区导航消失了，
  // 但「这份列表加载过没有」还得留着——纠错区就地改正文后要连带刷新它，
  // 否则切到管理区看到的是改前的旧数据。docs.length 不能替代它（库可能真的是空的）。
  const [manageLoaded, setManageLoaded] = useState(false)
  const [docs, setDocs] = useState<DocItem[]>([])
  const [changes, setChanges] = useState<ChangeItem[]>([])
  const [editing, setEditing] = useState<Record<string, string>>({})
  const [mgLoading, setMgLoading] = useState(false)

  async function loadManage() {
    setMgLoading(true)
    try {
      const [d, c] = await Promise.all([listDocs(), listChanges()])
      setDocs(d.docs); setChanges(c.changes)
      setManageLoaded(true)
    } catch (e) {
      setMsg({ type: 'err', text: '加载失败：' + (e as Error).message })
    } finally { setMgLoading(false) }
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
      if (manageLoaded) await loadManage()
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

  // ---- 奖赏钱规则维护 ----
  // 只维护规则，不碰任何个人数据。形态是带校验的 JSON 编辑器：
  // 规则 6 条、维护者 1 人，真正的约束全在后端 pydantic 里，做字段级表单只会两边漂移。
  const [rcText, setRcText] = useState('')             // 编辑区里的 JSON 原文
  const [rcVersion, setRcVersion] = useState<number | null>(null)  // 编辑区这份的版本号
  const [rcVersions, setRcVersions] = useState<RuleVersion[]>([])
  const [rcNote, setRcNote] = useState('')             // 改了什么，随 PUT 一起存
  const [rcErr, setRcErr] = useState('')               // 后端 detail 原样展示，不包装
  const [rcLoading, setRcLoading] = useState(false)

  // 版本列表按 version DESC，第一条就是最新版；编辑区显示的若不是它，说明在看历史版本
  const rcLatest = rcVersions.length > 0 ? rcVersions[0].version : rcVersion
  const rcHistoryView = rcVersion !== null && rcLatest !== null && rcVersion !== rcLatest

  // version 缺省取最新版。历史版本只读展示，不做回滚。
  async function loadRules(version?: number) {
    setRcLoading(true); setRcErr('')
    try {
      const r = await getAdminRules(version)
      setRcVersion(r.version)
      setRcText(JSON.stringify(r.ruleset, null, 2))
      const v = await listRuleVersions()
      setRcVersions(v.versions)
    } catch (e) {
      setRcErr((e as Error).message)
    } finally { setRcLoading(false) }
  }

  async function saveRules() {
    let parsed: RuleSet
    try {
      // 语法错在前端就拦下，不必往返一次
      parsed = JSON.parse(rcText)
    } catch (e) {
      setRcErr('JSON 语法错误（未发送请求）：' + (e as Error).message)
      return
    }
    setRcLoading(true); setRcErr('')
    try {
      const r = await putAdminRules(parsed, rcNote.trim())
      setMsg({ type: 'ok', text: `规则集已保存，当前第 ${r.version} 版` })
      setRcNote('')
      await loadRules()
    } catch (e) {
      // 422 的 detail 是 pydantic 的完整报错，里面的字段路径是定位问题的唯一线索，
      // 所以原样显示，不要包装成「保存失败」。校验不过不落库，旧版本仍在下发。
      setRcErr((e as Error).message)
    } finally { setRcLoading(false) }
  }

  // 切区时按需拉数据，等价于原来点「打开」时的那次加载。
  // 纠错队列每次进都刷——待处理条数是这块的意义所在，看到的必须是现在的。
  // 管理和规则只在没数据时拉一次，进去后想刷新有各自的按钮。
  async function go(s: SectionId) {
    setSection(s)
    if (s === 'corrections') await loadCorrections()
    if (s === 'manage' && !manageLoaded) await loadManage()
    if (s === 'rules' && rcVersion === null) await loadRules()
  }

  const banner = (
    <AnimatePresence>
      {msg && (
        <motion.div
          initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
          exit={{ opacity: 0, height: 0 }}
          className={`mb-5 rounded-xl px-4 py-2.5 text-sm border ${
            msg.type === 'ok'
              ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40'
              : 'bg-rose-500/15 text-rose-300 border-rose-500/40'}`}
        >
          {msg.text}
        </motion.div>
      )}
    </AnimatePresence>
  )

  return (
    <Shell
      section={section} onSection={go} pendingCount={pendingCount}
      token={token} onToken={saveToken}
      banner={banner}
    >
      {section === 'workbench' && (
        <Workbench
          url={url} title={title} rows={rows} rawText={rawText} showRaw={showRaw}
          loading={loading} parseProgress={parseProgress}
          question={question} turns={turns} asking={asking}
          onUrl={setUrl}
          onParse={handleParse}
          onRowChange={update}
          onIngest={handleIngest}
          onToggleRaw={() => setShowRaw(v => !v)}
          onQuestion={setQuestion}
          onAsk={handleAsk}
          onResetChat={resetChat}
        />
      )}

      {section === 'health' && (
        <Health
          running={hcRunning} progress={hcProgress} report={hcReport}
          onRun={runHealthCheck}
        />
      )}

      {section === 'corrections' && (
        <Corrections
          status={corrStatus} items={corrections} open={corrOpen}
          edit={corrEdit} note={corrNote} pendingCount={pendingCount}
          onStatus={switchCorrStatus}
          onToggle={id => setCorrOpen(o => ({ ...o, [id]: !o[id] }))}
          onEdit={(docId, text) => setCorrEdit(s => ({ ...s, [docId]: text }))}
          onCancelEdit={docId => setCorrEdit(s => { const n = { ...s }; delete n[docId]; return n })}
          onSaveDoc={saveCorrDoc}
          onNote={(id, text) => setCorrNote(n => ({ ...n, [id]: text }))}
          onResolve={markResolved}
        />
      )}

      {section === 'manage' && (
        <Manage
          docs={docs} changes={changes} editing={editing} loading={mgLoading}
          onEdit={(id, text) => setEditing(e => ({ ...e, [id]: text }))}
          onCancelEdit={id => setEditing(e => { const n = { ...e }; delete n[id]; return n })}
          onSave={saveDoc}
          onDelete={removeDoc}
          onReload={loadManage}
        />
      )}

      {section === 'rules' && (
        <Rules
          text={rcText} version={rcVersion} versions={rcVersions}
          note={rcNote} err={rcErr} loading={rcLoading} historyView={rcHistoryView}
          onText={setRcText}
          onNote={setRcNote}
          onSave={saveRules}
          onLoad={loadRules}
        />
      )}
    </Shell>
  )
}
