// 分区内共用的几个壳子。没有业务逻辑，只管排版与动效。
import { motion } from 'framer-motion'
import type { LucideIcon } from 'lucide-react'
import { ACCENTS, type Accent } from '../theme'

/** 内容卡片。原 App.tsx 里那个 Card 的加强版：多了 accent 描边与悬停微亮。 */
export function Card({
  children, accent, className = '', delay = 0,
}: {
  children: React.ReactNode
  /** 不传则用中性描边。传了就带这一区的主题色。 */
  accent?: Accent
  className?: string
  delay?: number
}) {
  const border = accent ? ACCENTS[accent].border : 'border-slate-700/60'
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.3 }}
      className={`rounded-2xl bg-slate-900/50 border ${border} backdrop-blur-sm
        p-5 shadow-2xl shadow-black/30 transition hover:bg-slate-900/60 ${className}`}
    >
      {children}
    </motion.div>
  )
}

/** 区标题：图标 + 渐变标题 + 副标题，右侧留一个操作位。 */
export function SectionHeader({
  icon: Icon, accent, title, subtitle, action,
}: {
  icon: LucideIcon
  accent: Accent
  title: string
  subtitle?: string
  action?: React.ReactNode
}) {
  const t = ACCENTS[accent]
  return (
    <div className="mb-6 flex items-end justify-between gap-4">
      <div className="flex items-center gap-3">
        <div className={`rounded-xl ${t.bgSoft} border ${t.border} p-2.5`}>
          <Icon size={20} strokeWidth={1.75} className={t.text} />
        </div>
        <div>
          <h2 className={`text-xl font-semibold tracking-tight bg-gradient-to-r ${t.title}
            bg-clip-text text-transparent`}>
            {title}
          </h2>
          {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
        </div>
      </div>
      {action}
    </div>
  )
}

/** 统计数字块。数字用 accent 渐变字，下面一行小标签。 */
export function Stat({
  value, label, accent, index = 0,
}: {
  value: number | string
  label: string
  accent: Accent
  index?: number
}) {
  const t = ACCENTS[accent]
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06 }}
      className={`flex-1 rounded-xl ${t.bgSoft} border ${t.border} px-4 py-3 text-center`}
    >
      <div className={`text-2xl font-semibold tabular-nums bg-gradient-to-br ${t.title}
        bg-clip-text text-transparent`}>
        {value}
      </div>
      <div className="mt-0.5 text-[11px] text-slate-500">{label}</div>
    </motion.div>
  )
}
