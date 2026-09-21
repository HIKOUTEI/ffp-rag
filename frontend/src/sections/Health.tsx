// 知识库体检。accent = teal。
//
// 四个统计数字保留各自的语义色（过期=琥珀、盲区=天蓝、矛盾=玫红）——
// 那是**状态色**不是 accent，颜色本身在传达信息，统一成 teal 反而丢东西。
import { motion } from 'framer-motion'
import { Stethoscope, Clock, CircleDashed, Swords, CheckCircle2 } from 'lucide-react'
import { Card, SectionHeader, Stat } from '../layout/ui'
import type { HealthReport } from '../api'

export function Health({
  running, progress, report, onRun,
}: {
  running: boolean
  progress: string
  report: HealthReport | null
  onRun: () => void
}) {
  return (
    <>
      <SectionHeader
        icon={Stethoscope} accent="teal"
        title="知识库体检"
        subtitle="时效性 / 覆盖盲区 / 矛盾冲突"
        action={
          <button
            onClick={onRun} disabled={running}
            className="rounded-lg px-4 py-2 text-sm font-medium bg-teal-500 hover:bg-teal-400
              disabled:opacity-50 transition shadow-lg shadow-teal-500/20"
          >
            {running ? '体检中…' : '开始体检'}
          </button>
        }
      />

      {running && (
        <Card accent="teal" className="mb-4">
          <div className="flex items-center gap-2 text-sm text-teal-300">
            <span className="inline-block h-3.5 w-3.5 rounded-full border-2 border-teal-400
              border-t-transparent animate-spin" />
            {progress}
          </div>
        </Card>
      )}

      {!running && !report && (
        <Card accent="teal">
          <div className="py-10 text-center">
            <Stethoscope size={32} strokeWidth={1.5} className="mx-auto text-teal-400/50" />
            <div className="mt-3 text-sm text-slate-400">还没跑过体检</div>
            <div className="mt-1 text-xs text-slate-600">
              会扫一遍库里的知识，找出可能过期的、用户会问但库里缺的、以及互相矛盾的
            </div>
          </div>
        </Card>
      )}

      {report && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-3">
            <Stat value={report.total_docs} label="条知识" accent="teal" index={0} />
            <Stat value={report.summary.stale_count} label="可能过期" accent="amber" index={1} />
            <Stat value={report.summary.gap_count} label="覆盖盲区" accent="sky" index={2} />
            <Stat value={report.summary.conflict_count} label="矛盾冲突" accent="rose" index={3} />
          </div>

          {report.timeliness.length > 0 && (
            <Card accent="amber">
              <div className="flex items-center gap-2 mb-3 text-sm font-medium text-amber-300">
                <Clock size={16} strokeWidth={1.75} />
                需复核（可能过期）
              </div>
              <ul className="space-y-1.5">
                {report.timeliness.map((f, i) => (
                  <motion.li
                    key={i}
                    initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.03 }}
                    className="text-xs text-slate-300 rounded-lg bg-amber-500/10 border
                      border-amber-500/30 px-3 py-2"
                  >
                    <span className="text-amber-400 font-medium">{f.months}月前</span> · {f.reason}
                    <div className="text-slate-400 mt-0.5 leading-relaxed">{f.text}…</div>
                  </motion.li>
                ))}
              </ul>
            </Card>
          )}

          {report.completeness.gaps.length > 0 && (
            <Card accent="sky">
              <div className="flex items-center gap-2 mb-3 text-sm font-medium text-sky-300">
                <CircleDashed size={16} strokeWidth={1.75} />
                覆盖盲区
                <span className="text-xs font-normal text-slate-500">
                  用户可能会问，但库里缺 · 基线 {report.completeness.total_questions} 题
                </span>
              </div>
              <ul className="flex flex-wrap gap-1.5">
                {report.completeness.gaps.map((g, i) => (
                  <motion.li
                    key={i}
                    initial={{ opacity: 0, scale: 0.94 }} animate={{ opacity: 1, scale: 1 }}
                    transition={{ delay: i * 0.02 }}
                    className="text-xs text-sky-200 rounded-full bg-sky-500/10 border
                      border-sky-500/30 px-3 py-1.5"
                  >
                    {g.question}
                  </motion.li>
                ))}
              </ul>
            </Card>
          )}

          {report.consistency.length > 0 && (
            <Card accent="rose">
              <div className="flex items-center gap-2 mb-3 text-sm font-medium text-rose-300">
                <Swords size={16} strokeWidth={1.75} />
                矛盾冲突
              </div>
              <ul className="space-y-2">
                {report.consistency.map((c, i) => (
                  <li
                    key={i}
                    className="text-xs rounded-lg bg-rose-500/10 border border-rose-500/30 px-3 py-2"
                  >
                    <div className="text-rose-300 font-medium">{c.reason}</div>
                    <div className="text-slate-400 mt-1 leading-relaxed">
                      A（{c.a_source}）：{c.a}…
                    </div>
                    <div className="text-slate-400 leading-relaxed">
                      B（{c.b_source}）：{c.b}…
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {report.summary.stale_count === 0 && report.summary.gap_count === 0
            && report.summary.conflict_count === 0 && (
            <Card accent="emerald">
              <div className="flex items-center justify-center gap-2 py-6 text-sm text-emerald-300">
                <CheckCircle2 size={18} strokeWidth={1.75} />
                未发现问题，知识库很健康
              </div>
            </Card>
          )}
        </div>
      )}
    </>
  )
}
