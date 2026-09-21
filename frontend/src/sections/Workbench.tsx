// 工作台：入库（sky）+ 问答（violet）双栏并排。
//
// 这两块必须并排，是本区存在的全部理由——日常主流程是
// 「粘 URL → 入库 → 立刻问一句验证进没进去」，原来这个验证要滚整屏。
//
// 本文件里的纯函数是**展示辅助**，跟着 JSX 从 App.tsx 一起搬过来的，不含状态。
import { motion, AnimatePresence } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Link2, MessagesSquare, ChevronDown, FileText, Eraser, Send, TriangleAlert,
} from 'lucide-react'
import { Card } from '../layout/ui'
import type { Fragment, ChatSource, ChatMessage } from '../api'

export interface Row extends Fragment { checked: boolean }

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

export function Workbench({
  url, title, rows, rawText, showRaw, loading, parseProgress,
  question, turns, asking,
  onUrl, onParse, onRowChange, onIngest, onToggleRaw,
  onQuestion, onAsk, onResetChat,
}: {
  url: string
  title: string
  rows: Row[]
  rawText: string
  showRaw: boolean
  loading: boolean
  parseProgress: string
  question: string
  turns: { msg: ChatMessage; sources?: ChatSource[] }[]
  asking: boolean
  onUrl: (v: string) => void
  onParse: () => void
  onRowChange: (i: number, patch: Partial<Row>) => void
  onIngest: () => void
  onToggleRaw: () => void
  onQuestion: (v: string) => void
  onAsk: () => void
  onResetChat: () => void
}) {
  const checkedCount = rows.filter(r => r.checked).length

  return (
    <div className="grid gap-4 lg:grid-cols-2 items-start">
      {/* ───────────── 入库 ───────────── */}
      <Card accent="sky">
        <div className="flex items-center gap-2 mb-4">
          <div className="rounded-lg bg-sky-500/10 border border-sky-500/30 p-2">
            <Link2 size={16} strokeWidth={1.75} className="text-sky-300" />
          </div>
          <div>
            <div className="text-sm font-semibold bg-gradient-to-r from-sky-200 to-sky-400
              bg-clip-text text-transparent">入库</div>
            <div className="text-[11px] text-slate-600">传 URL → 审核片段 → 进库</div>
          </div>
        </div>

        <div className="flex gap-2">
          <input
            value={url} onChange={e => onUrl(e.target.value)}
            onKeyDown={e => { if (isSubmitEnter(e)) { e.preventDefault(); onParse() } }}
            placeholder="粘贴文章 URL（公众号图文 / 普通网页；小红书不支持）"
            className="flex-1 rounded-lg bg-slate-950/70 border border-slate-700 px-3 py-2.5
              text-sm outline-none focus:border-sky-500 transition"
          />
          <button
            onClick={onParse} disabled={loading}
            className="shrink-0 rounded-lg px-5 py-2.5 text-sm font-medium bg-sky-500
              hover:bg-sky-400 disabled:opacity-50 transition shadow-lg shadow-sky-500/20"
          >
            {loading ? '解析中…' : '解析'}
          </button>
        </div>

        {loading && parseProgress && (
          <div className="mt-2.5 flex items-center gap-2 text-xs text-sky-300">
            <span className="inline-block h-3 w-3 rounded-full border-2 border-sky-400
              border-t-transparent animate-spin" />
            {parseProgress}
          </div>
        )}

        {rows.length === 0 && !loading && (
          <div className="py-12 text-center">
            <Link2 size={28} strokeWidth={1.5} className="mx-auto text-sky-400/40" />
            <div className="mt-3 text-xs text-slate-600">
              解析后的片段会出现在这里，逐条审核再入库
            </div>
          </div>
        )}

        <AnimatePresence>
          {rows.length > 0 && (
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="mt-4"
            >
              <div className="flex items-center justify-between gap-3 mb-3">
                <div className="min-w-0 text-xs text-slate-400">
                  <span className="text-slate-600">来源：</span>
                  <span className="text-slate-300">{title}</span>
                  <span className="ml-2 text-slate-600 tabular-nums">
                    {rows.length} 段，选中 {checkedCount}
                  </span>
                </div>
                <button
                  onClick={onIngest} disabled={loading || checkedCount === 0}
                  className="shrink-0 rounded-lg px-4 py-2 text-xs font-medium bg-emerald-500
                    hover:bg-emerald-400 disabled:opacity-40 transition shadow-lg shadow-emerald-500/20"
                >
                  入库选中项
                </button>
              </div>

              {rawText && (
                <div className="mb-3">
                  <button
                    onClick={onToggleRaw}
                    className="flex items-center gap-1 text-xs text-sky-400 hover:text-sky-300 transition"
                  >
                    <ChevronDown
                      size={13} strokeWidth={2}
                      className={`transition-transform ${showRaw ? 'rotate-180' : ''}`}
                    />
                    <FileText size={12} strokeWidth={2} />
                    {showRaw ? '收起原文' : '查看抓取到的原文（对照 AI 归纳）'}
                  </button>
                  <AnimatePresence>
                    {showRaw && (
                      <motion.pre
                        initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                        className="mt-2 max-h-72 overflow-auto rounded-lg bg-slate-950/70 border
                          border-slate-800 px-3 py-2 text-xs leading-relaxed text-slate-300
                          whitespace-pre-wrap"
                      >
                        {rawText}
                      </motion.pre>
                    )}
                  </AnimatePresence>
                </div>
              )}

              <div className="space-y-2.5 max-h-[32rem] overflow-y-auto pr-1">
                {rows.map((r, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: Math.min(i, 10) * 0.03 }}
                    className={`rounded-xl border p-3.5 transition ${r.checked
                      ? 'bg-slate-950/60 border-slate-700'
                      : 'bg-slate-950/30 border-slate-800 opacity-60'}`}
                  >
                    <div className="flex items-start gap-3">
                      <input
                        type="checkbox" checked={r.checked}
                        onChange={e => onRowChange(i, { checked: e.target.checked })}
                        className="mt-1.5 h-4 w-4 accent-emerald-500 shrink-0"
                      />
                      <div className="flex-1 min-w-0 space-y-2">
                        <div className="flex gap-2 items-center">
                          <select
                            value={r.domain} onChange={e => onRowChange(i, { domain: e.target.value })}
                            className={`shrink-0 rounded-md border px-2 py-1 text-xs font-medium
                              outline-none ${DOMAIN_COLOR[r.domain] || DOMAIN_COLOR.other}`}
                          >
                            {DOMAINS.map(d => (
                              <option key={d} value={d} className="bg-slate-800 text-slate-100">
                                {DOMAIN_LABEL[d]}
                              </option>
                            ))}
                          </select>
                          <input
                            value={r.source} onChange={e => onRowChange(i, { source: e.target.value })}
                            placeholder="来源标签"
                            className="flex-1 min-w-0 rounded-md bg-slate-950/70 border border-slate-700
                              px-2 py-1 text-xs outline-none focus:border-sky-500"
                          />
                          <input
                            value={r.subtopic || ''}
                            onChange={e => onRowChange(i, { subtopic: e.target.value })}
                            placeholder="细分"
                            className="w-20 shrink-0 rounded-md bg-teal-500/10 border border-teal-500/40
                              text-teal-300 px-2 py-1 text-xs outline-none focus:border-teal-400"
                          />
                        </div>
                        <textarea
                          value={r.text} onChange={e => onRowChange(i, { text: e.target.value })}
                          rows={3}
                          className="w-full rounded-md bg-slate-950/70 border border-slate-700 px-3 py-2
                            text-sm leading-relaxed outline-none focus:border-sky-500 resize-y"
                        />
                        {r.duplicate && (
                          <div className="rounded-lg bg-amber-500/10 border border-amber-500/40
                            px-3 py-2 text-xs text-amber-300">
                            <div className="flex items-center gap-1.5">
                              <TriangleAlert size={12} strokeWidth={2} className="shrink-0" />
                              与已有内容相似（{(r.duplicate.score * 100).toFixed(0)}%）
                              <span className="text-amber-400/70 truncate">
                                ，来自「{r.duplicate.source}」
                                {r.duplicate.date ? ` · ${r.duplicate.date}` : ''}
                              </span>
                            </div>
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
      </Card>

      {/* ───────────── 问答 ───────────── */}
      <Card accent="violet" delay={0.08}>
        <div className="flex items-center justify-between gap-2 mb-4">
          <div className="flex items-center gap-2">
            <div className="rounded-lg bg-violet-500/10 border border-violet-500/30 p-2">
              <MessagesSquare size={16} strokeWidth={1.75} className="text-violet-300" />
            </div>
            <div>
              <div className="text-sm font-semibold bg-gradient-to-r from-violet-200 to-violet-400
                bg-clip-text text-transparent">问答</div>
              <div className="text-[11px] text-slate-600">可连续追问，如「那云闪付呢？」</div>
            </div>
          </div>
          {turns.length > 0 && (
            <button
              onClick={onResetChat}
              className="flex items-center gap-1 text-xs text-slate-600 hover:text-slate-400 transition"
            >
              <Eraser size={12} strokeWidth={2} />清空
            </button>
          )}
        </div>

        {turns.length === 0 ? (
          <div className="py-12 text-center">
            <MessagesSquare size={28} strokeWidth={1.5} className="mx-auto text-violet-400/40" />
            <div className="mt-3 text-xs text-slate-600">
              刚入库的知识，在这里问一句就能验证进没进去
            </div>
          </div>
        ) : (
          <div className="mb-3 space-y-3 max-h-[34rem] overflow-y-auto pr-1">
            {turns.map((t, i) => t.msg.role === 'user' ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-violet-500/20 border
                  border-violet-500/40 px-3.5 py-2 text-sm text-violet-100">
                  {t.msg.content}
                </div>
              </div>
            ) : (
              <motion.div
                key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                className="flex justify-start"
              >
                <div className="max-w-[92%] rounded-2xl rounded-bl-sm bg-slate-950/70 border
                  border-slate-800 px-4 py-3 text-[15px] leading-7 text-slate-100">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                      ul: ({ children }) => <ul className="my-2 space-y-1.5 list-none">{children}</ul>,
                      li: ({ children }) => (
                        <li className="flex gap-2">
                          <span className="text-violet-400 mt-0.5">•</span>
                          <span className="flex-1">{children}</span>
                        </li>
                      ),
                      strong: ({ children }) => (
                        <strong className="font-semibold text-violet-300">{children}</strong>
                      ),
                      a: ({ href, children }) => (
                        <a href={href} target="_blank" rel="noreferrer"
                          className="text-violet-400 underline">{children}</a>
                      ),
                    }}
                  >
                    {fixMarkdownBold(t.msg.content)}
                  </ReactMarkdown>
                  {t.sources && uniqSources(t.sources).length > 0 && (
                    <div className="mt-2.5 pt-2.5 border-t border-slate-800 flex flex-wrap
                      items-center gap-2">
                      <span className="text-xs text-slate-600">来源：</span>
                      {uniqSources(t.sources).map((s, j) => s.url ? (
                        <a key={j} href={s.url} target="_blank" rel="noreferrer"
                          className="inline-flex items-center gap-1 rounded-full bg-violet-500/15
                            hover:bg-violet-500/25 text-violet-300 border border-violet-500/40
                            px-2.5 py-1 text-xs transition">
                          <FileText size={11} strokeWidth={2} />
                          {s.source}
                          {s.date && (
                            <span className={isStale(s.date) ? 'text-amber-400' : 'text-violet-400/60'}>
                              · {s.date}{isStale(s.date) ? ' ⚠︎' : ''}
                            </span>
                          )}
                        </a>
                      ) : (
                        <span key={j} className="inline-flex items-center gap-1 rounded-full
                          bg-slate-800 text-slate-400 border border-slate-700 px-2.5 py-1 text-xs">
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
                <div className="rounded-2xl rounded-bl-sm bg-slate-950/70 border border-slate-800
                  px-3.5 py-2.5 text-sm text-slate-500">
                  思考中…
                </div>
              </div>
            )}
          </div>
        )}

        <div className="flex gap-2">
          <input
            value={question} onChange={e => onQuestion(e.target.value)}
            onKeyDown={e => { if (isSubmitEnter(e)) { e.preventDefault(); onAsk() } }}
            placeholder={turns.length ? '继续追问…' : '问一个问题，如：国航金卡有哪些权益？'}
            className="flex-1 min-w-0 rounded-lg bg-slate-950/70 border border-slate-700 px-3 py-2.5
              text-sm outline-none focus:border-violet-500 transition"
          />
          <button
            onClick={onAsk} disabled={asking}
            className="shrink-0 flex items-center gap-1.5 rounded-lg px-4 py-2.5 text-sm font-medium
              bg-violet-500 hover:bg-violet-400 disabled:opacity-50 transition
              shadow-lg shadow-violet-500/20"
          >
            <Send size={14} strokeWidth={2} />
            {asking ? '思考中…' : '发送'}
          </button>
        </div>
      </Card>
    </div>
  )
}
