// 知识管理。accent = amber。
//
// 宽屏下拆成双栏：知识列表占 2 份，变更记录占 1 份常驻右侧。
// 原来两块上下堆在一张卡里、各自 max-h 滚动，宽屏上白白浪费右半边。
import { motion } from 'framer-motion'
import { Database, Plus, Pencil, X, RefreshCw, Trash2 } from 'lucide-react'
import { Card, SectionHeader } from '../layout/ui'
import type { DocItem, ChangeItem } from '../api'

export function Manage({
  docs, changes, editing, loading,
  onEdit, onCancelEdit, onSave, onDelete, onReload,
}: {
  docs: DocItem[]
  changes: ChangeItem[]
  editing: Record<string, string>
  loading: boolean
  /** 进入编辑态和编辑中打字都走它：写 editing[id]，有值即为编辑中 */
  onEdit: (id: string, text: string) => void
  onCancelEdit: (id: string) => void
  onSave: (id: string) => void
  onDelete: (id: string) => void
  onReload: () => void
}) {
  return (
    <>
      <SectionHeader
        icon={Database} accent="amber"
        title="知识管理"
        subtitle="编辑 / 删除 / 变更记录"
        action={
          <button
            onClick={onReload} disabled={loading}
            className="flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-sm bg-slate-800
              hover:bg-slate-700 disabled:opacity-50 transition"
          >
            <RefreshCw size={14} strokeWidth={2} className={loading ? 'animate-spin' : ''} />
            {loading ? '加载中…' : '刷新'}
          </button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        {/* 知识列表 */}
        <div className="lg:col-span-2">
          <Card accent="amber">
            <div className="mb-3 text-sm font-medium text-slate-300">
              库中知识
              <span className="ml-2 text-xs text-slate-500 tabular-nums">{docs.length} 条</span>
            </div>
            {docs.length === 0 && !loading && (
              <div className="py-10 text-center text-xs text-slate-600">库里还没有知识</div>
            )}
            <div className="space-y-2 max-h-[34rem] overflow-y-auto pr-1">
              {docs.map((d, i) => {
                const isEditing = editing[d.id] !== undefined
                return (
                  <motion.div
                    key={d.id}
                    initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: Math.min(i, 12) * 0.02 }}
                    className={`rounded-xl border px-3.5 py-3 transition ${isEditing
                      ? 'bg-slate-950/70 border-amber-500/50'
                      : 'bg-slate-950/50 border-slate-800 hover:border-slate-700'}`}
                  >
                    <div className="flex items-center gap-2 mb-1.5 text-xs">
                      <span className="rounded bg-slate-800 px-1.5 py-0.5 text-slate-300">
                        {d.domain}
                      </span>
                      {d.subtopic && (
                        <span className="rounded bg-teal-500/15 text-teal-300 px-1.5 py-0.5">
                          {d.subtopic}
                        </span>
                      )}
                      <span className="text-slate-600 truncate flex-1">
                        {d.source}{d.date ? ` · ${d.date}` : ''}
                      </span>
                    </div>
                    {isEditing ? (
                      <textarea
                        value={editing[d.id]}
                        onChange={e => onEdit(d.id, e.target.value)}
                        rows={4}
                        className="w-full rounded-lg bg-slate-950 border border-amber-500/50 px-3 py-2
                          text-xs leading-relaxed outline-none resize-y"
                      />
                    ) : (
                      <div className="text-xs text-slate-300 leading-relaxed">{d.text}</div>
                    )}
                    <div className="flex gap-3 mt-2">
                      {isEditing ? (
                        <>
                          <button
                            onClick={() => onSave(d.id)}
                            className="text-xs text-emerald-400 hover:text-emerald-300"
                          >保存</button>
                          <button
                            onClick={() => onCancelEdit(d.id)}
                            className="text-xs text-slate-500 hover:text-slate-400"
                          >取消</button>
                        </>
                      ) : (
                        <>
                          <button
                            onClick={() => onEdit(d.id, d.text)}
                            className="flex items-center gap-1 text-xs text-sky-400 hover:text-sky-300"
                          >
                            <Pencil size={11} strokeWidth={2} />编辑
                          </button>
                          <button
                            onClick={() => onDelete(d.id)}
                            className="flex items-center gap-1 text-xs text-rose-400 hover:text-rose-300"
                          >
                            <Trash2 size={11} strokeWidth={2} />删除
                          </button>
                        </>
                      )}
                    </div>
                  </motion.div>
                )
              })}
            </div>
          </Card>
        </div>

        {/* 变更流水 */}
        <Card accent="amber" delay={0.08}>
          <div className="mb-3 text-sm font-medium text-slate-300">变更记录</div>
          {changes.length === 0 ? (
            <div className="py-10 text-center text-xs text-slate-600">暂无变更</div>
          ) : (
            <ul className="space-y-2 max-h-[34rem] overflow-y-auto pr-1">
              {changes.map((c, i) => (
                <li key={i} className="flex gap-2.5 text-xs">
                  <span className={`mt-0.5 shrink-0 ${
                    c.action === 'add' ? 'text-emerald-400'
                      : c.action === 'update' ? 'text-sky-400' : 'text-rose-400'}`}>
                    {c.action === 'add' ? <Plus size={12} strokeWidth={2.5} />
                      : c.action === 'update' ? <Pencil size={12} strokeWidth={2.5} />
                      : <X size={12} strokeWidth={2.5} />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-slate-400 leading-relaxed">{c.summary}</div>
                    <div className="text-[10px] text-slate-600 tabular-nums mt-0.5">
                      {c.at.slice(5, 16).replace('T', ' ')}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  )
}
