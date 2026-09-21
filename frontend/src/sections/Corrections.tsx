// 纠错队列。accent = rose。
//
// 首次加载不在这里做——切到本区时由 App.tsx 触发，等价于原来的 toggleCorr。
import { motion } from 'framer-motion'
import { AlertTriangle, CheckCircle2, ChevronRight } from 'lucide-react'
import { Card, SectionHeader } from '../layout/ui'
import type { CorrectionItem } from '../api'

export function Corrections({
  status, items, open, edit, note, pendingCount,
  onStatus, onToggle, onEdit, onCancelEdit, onSaveDoc, onNote, onResolve,
}: {
  status: 'pending' | 'all'
  items: CorrectionItem[]
  open: Record<number, boolean>
  edit: Record<string, string>
  note: Record<number, string>
  pendingCount: number
  onStatus: (s: 'pending' | 'all') => void
  onToggle: (id: number) => void
  onEdit: (docId: string, text: string) => void
  onCancelEdit: (docId: string) => void
  onSaveDoc: (docId: string) => void
  onNote: (id: number, text: string) => void
  onResolve: (id: number) => void
}) {
  return (
    <>
      <SectionHeader
        icon={AlertTriangle} accent="rose"
        title="纠错队列"
        subtitle="用户报错 → 修正知识"
        action={
          <div className="flex items-center gap-3">
            {pendingCount > 0 && (
              <span className="rounded-full bg-rose-500/20 text-rose-300 px-3 py-1 text-xs">
                {pendingCount} 待处理
              </span>
            )}
            <div className="flex gap-1 rounded-lg bg-slate-900/60 p-1">
              {(['pending', 'all'] as const).map(s => (
                <button
                  key={s} onClick={() => onStatus(s)}
                  className={`rounded-md px-3 py-1 text-xs transition ${status === s
                    ? 'bg-rose-500/20 text-rose-300'
                    : 'text-slate-500 hover:text-slate-300'}`}
                >
                  {s === 'pending' ? '待处理' : '全部'}
                </button>
              ))}
            </div>
          </div>
        }
      />

      {items.length === 0 ? (
        <Card accent="emerald">
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-emerald-300">
            <CheckCircle2 size={18} strokeWidth={1.75} />
            没有待处理的报错
          </div>
        </Card>
      ) : (
        <ul className="space-y-3">
          {items.map((c, idx) => (
            <motion.li
              key={c.id}
              initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
              transition={{ delay: idx * 0.03 }}
              className="rounded-2xl bg-slate-900/50 border border-rose-500/20 backdrop-blur-sm
                overflow-hidden transition hover:border-rose-500/40"
            >
              <div
                className="cursor-pointer px-5 py-4"
                onClick={() => onToggle(c.id)}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-2.5 min-w-0">
                    <ChevronRight
                      size={16} strokeWidth={2}
                      className={`mt-0.5 shrink-0 text-slate-600 transition-transform
                        ${open[c.id] ? 'rotate-90' : ''}`}
                    />
                    <div className="min-w-0">
                      <div className="text-sm text-slate-200">{c.question}</div>
                      {c.note
                        ? <div className="mt-1 text-xs text-rose-300">用户说：{c.note}</div>
                        : <div className="mt-1 text-xs text-slate-600">（用户未填说明）</div>}
                      {c.status === 'done' && (
                        <div className="mt-1.5 inline-flex items-center gap-1 rounded-full
                          bg-emerald-500/15 text-emerald-300 px-2 py-0.5 text-[11px]">
                          <CheckCircle2 size={11} strokeWidth={2} />
                          已处理{c.resolution ? '：' + c.resolution : ''}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="shrink-0 text-[11px] text-slate-600 tabular-nums">
                    {c.created_at}
                  </div>
                </div>
              </div>

              {open[c.id] && (
                <motion.div
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                  className="border-t border-slate-800 px-5 py-4 space-y-3"
                >
                  {c.rewritten && c.rewritten !== c.question && (
                    <div className="text-[11px] text-slate-600">检索问题：{c.rewritten}</div>
                  )}
                  <div className="text-xs text-slate-400 whitespace-pre-wrap max-h-48 overflow-y-auto
                    rounded-lg bg-slate-950/60 border border-slate-800 px-3 py-2 leading-relaxed">
                    {c.answer || '（无回答快照）'}
                  </div>

                  {c.docs.length === 0 ? (
                    <div className="text-xs text-amber-300 rounded-lg bg-amber-500/10 border
                      border-amber-500/30 px-3 py-2">
                      无关联知识（可能是库里缺这条）—— 考虑去工作台走 URL 摄入补录
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <div className="text-[11px] font-medium text-slate-500">
                        命中的知识（可就地修改）
                      </div>
                      {c.docs.map(d => d.missing ? (
                        <div key={d.id} className="text-xs text-slate-600 italic">
                          {d.id} —— 已被删除
                        </div>
                      ) : (
                        <div key={d.id} className="rounded-lg bg-slate-950/60 border border-slate-800
                          px-3 py-2">
                          <textarea
                            value={edit[d.id] !== undefined ? edit[d.id] : d.text}
                            onChange={e => onEdit(d.id, e.target.value)}
                            rows={3}
                            className="w-full bg-transparent text-xs text-slate-300 outline-none
                              resize-y leading-relaxed"
                          />
                          <div className="flex items-center gap-3 mt-1">
                            <span className="text-[10px] text-slate-600">{d.meta?.source}</span>
                            {edit[d.id] !== undefined && (
                              <>
                                <button
                                  onClick={() => onSaveDoc(d.id)}
                                  className="text-xs text-emerald-400 hover:text-emerald-300"
                                >保存</button>
                                <button
                                  onClick={() => onCancelEdit(d.id)}
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
                        value={note[c.id] || ''}
                        onChange={e => onNote(c.id, e.target.value)}
                        placeholder="处理备注：改了什么 / 为什么不用改"
                        className="flex-1 rounded-lg bg-slate-950/60 border border-slate-700 px-3 py-1.5
                          text-xs outline-none focus:border-rose-500 transition"
                      />
                      <button
                        onClick={() => onResolve(c.id)}
                        className="rounded-lg px-4 py-1.5 text-xs font-medium bg-emerald-600
                          hover:bg-emerald-500 transition"
                      >
                        标记已处理
                      </button>
                    </div>
                  )}
                </motion.div>
              )}
            </motion.li>
          ))}
        </ul>
      )}
    </>
  )
}
