// 返现规则维护。accent = emerald。
//
// 形态是带校验的 JSON 编辑器：规则 6 条、维护者 1 人，真正的约束全在后端 pydantic 里，
// 做字段级表单只会两边漂移（ADR-0009）。
//
// `err` 必须用 <pre> 原样展示——422 的 detail 是 pydantic 的完整报错，
// 里面的字段路径是定位问题的唯一线索，包装成「保存失败」等于把它扔了。
import { Percent, History, AlertCircle } from 'lucide-react'
import { Card, SectionHeader } from '../layout/ui'
import type { RuleVersion } from '../api'

export function Rules({
  text, version, versions, note, err, loading, historyView,
  onText, onNote, onSave, onLoad,
}: {
  text: string
  version: number | null
  versions: RuleVersion[]
  note: string
  err: string
  loading: boolean
  historyView: boolean
  onText: (t: string) => void
  onNote: (t: string) => void
  onSave: () => void
  onLoad: (version?: number) => void
}) {
  return (
    <>
      <SectionHeader
        icon={Percent} accent="emerald"
        title="返现规则"
        subtitle="奖赏钱规则集 · JSON 整份替换，校验不过不落库"
        action={
          version !== null && (
            <span className={`rounded-full px-3 py-1 text-xs ${historyView
              ? 'bg-amber-500/20 text-amber-300'
              : 'bg-emerald-500/20 text-emerald-300'}`}>
              第 {version} 版{historyView ? '（历史）' : '（当前）'}
            </span>
          )
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-4">
          {historyView && (
            <div className="flex items-center gap-3 rounded-xl bg-amber-500/10 border
              border-amber-500/30 px-4 py-2.5 text-xs text-amber-300">
              <AlertCircle size={14} strokeWidth={2} className="shrink-0" />
              正在查看第 {version} 版（只读，不做回滚）
              <button
                onClick={() => onLoad()}
                className="ml-auto shrink-0 text-amber-200 underline hover:text-amber-100"
              >
                回到最新版
              </button>
            </div>
          )}

          <Card accent="emerald">
            <textarea
              value={text} onChange={e => onText(e.target.value)}
              readOnly={historyView}
              rows={26} spellCheck={false}
              placeholder="规则集 JSON：{ categories: [...], rules: [...] }"
              className={`w-full rounded-lg bg-slate-950/80 border border-slate-800 px-4 py-3
                font-mono text-xs leading-relaxed outline-none focus:border-emerald-500/60
                resize-y transition ${historyView ? 'text-slate-500' : 'text-slate-200'}`}
            />

            {err && (
              <pre className="mt-3 rounded-lg bg-rose-500/10 border border-rose-500/40 px-3 py-2.5
                text-xs text-rose-300 whitespace-pre-wrap max-h-60 overflow-auto leading-relaxed">
                {err}
              </pre>
            )}

            {!historyView && (
              <div className="mt-3 flex gap-2">
                <input
                  value={note} onChange={e => onNote(e.target.value)}
                  placeholder="备注：这一版改了什么"
                  className="flex-1 rounded-lg bg-slate-950/60 border border-slate-700 px-3 py-2
                    text-xs outline-none focus:border-emerald-500 transition"
                />
                <button
                  onClick={onSave} disabled={loading}
                  className="rounded-lg px-4 py-2 text-xs font-medium bg-emerald-600
                    hover:bg-emerald-500 disabled:opacity-50 transition shadow-lg shadow-emerald-500/20"
                >
                  {loading ? '处理中…' : '保存新版本'}
                </button>
              </div>
            )}
          </Card>
        </div>

        <Card accent="emerald" delay={0.08}>
          <div className="flex items-center gap-2 mb-3 text-sm font-medium text-slate-300">
            <History size={15} strokeWidth={1.75} className="text-emerald-400" />
            版本记录
          </div>
          <div className="mb-2 text-[11px] text-slate-600">点一条查看那一版的 JSON</div>
          <ul className="space-y-1 max-h-[34rem] overflow-y-auto pr-1">
            {versions.map(v => (
              <li
                key={v.version}
                onClick={() => onLoad(v.version)}
                className={`cursor-pointer rounded-lg px-3 py-2 text-xs transition ${
                  v.version === version
                    ? 'bg-emerald-500/15 text-emerald-200 border border-emerald-500/40'
                    : 'text-slate-400 border border-transparent hover:bg-slate-800/60'}`}
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono shrink-0">v{v.version}</span>
                  <span className="text-slate-600 tabular-nums text-[10px]">
                    {v.updated_at.slice(0, 16).replace('T', ' ')}
                  </span>
                </div>
                <div className="mt-0.5 truncate">{v.note || '（无备注）'}</div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  )
}
