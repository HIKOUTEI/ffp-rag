// 侧栏：三组导航 + 底部令牌状态栏。
//
// 令牌不是导航项。改成分区导航后它藏了两层，而新环境第一次打开时它是**唯一**的出路
// ——`api.ts` 里除问答外所有请求都带 `Authorization`，没填就满屏 401。
// 所以做成常驻状态栏：没填时变琥珀色并带呼吸动画，在哪一页都看得见。
import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Sparkles, Stethoscope, AlertTriangle,
  Database, Percent, KeyRound, ChevronDown, type LucideIcon,
} from 'lucide-react'
import { ACCENTS, SECTION_ACCENT, type SectionId } from '../theme'

interface NavItem {
  id: SectionId
  icon: LucideIcon
  label: string
}

// 分组依据是代码里已有的事实，不是新发明的：showManage / showCorr / showRules
// 三块默认收起，常驻可见的只有令牌、入库、问答。日常主流程是
// 「粘 URL → 入库 → 立刻问一句验证进没进去」，所以入库与问答合成一个工作台。
const GROUPS: { title: string; items: NavItem[] }[] = [
  {
    title: '工作台',
    items: [{ id: 'workbench', icon: Sparkles, label: '入库 + 问答' }],
  },
  {
    title: '知识维护',
    items: [
      { id: 'health', icon: Stethoscope, label: '体检' },
      { id: 'corrections', icon: AlertTriangle, label: '纠错' },
      { id: 'manage', icon: Database, label: '管理' },
    ],
  },
  {
    title: '系统',
    items: [{ id: 'rules', icon: Percent, label: '返现规则' }],
  },
]

export function Sidebar({
  section, onSection, pendingCount, token, onToken,
}: {
  section: SectionId
  onSection: (s: SectionId) => void
  pendingCount: number
  token: string
  onToken: (t: string) => void
}) {
  // 纯 UI 状态，与业务无关，所以留在本组件内而不是提到 App.tsx
  const [tokenOpen, setTokenOpen] = useState(false)

  return (
    <div className="flex h-full flex-col bg-slate-950/70 backdrop-blur-xl">
      <div className="px-5 pt-6 pb-5">
        <div className="text-lg font-bold tracking-tight bg-gradient-to-r from-sky-300 to-violet-300
          bg-clip-text text-transparent">
          ffp-rag
        </div>
        <div className="text-[11px] text-slate-600 mt-0.5">常旅客知识库 · 控制台</div>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 pb-4 space-y-5">
        {GROUPS.map(g => (
          <div key={g.title}>
            <div className="px-2 mb-1.5 text-[10px] font-medium uppercase tracking-widest text-slate-600">
              {g.title}
            </div>
            <div className="space-y-0.5">
              {g.items.map(item => {
                const active = section === item.id
                const t = ACCENTS[SECTION_ACCENT[item.id]]
                return (
                  <button
                    key={item.id}
                    onClick={() => onSection(item.id)}
                    className={`relative w-full flex items-center gap-2.5 rounded-lg px-2.5 py-2
                      text-sm transition ${active
                        ? `${t.bgSoft} ${t.text}`
                        : 'text-slate-400 hover:bg-slate-800/50 hover:text-slate-200'}`}
                  >
                    {active && (
                      <motion.span
                        layoutId="nav-bar"
                        className={`absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full ${t.bar}`}
                      />
                    )}
                    <item.icon size={16} strokeWidth={1.75} />
                    <span className="flex-1 text-left">{item.label}</span>
                    {item.id === 'corrections' && pendingCount > 0 && (
                      <span className="rounded-full bg-rose-500/20 text-rose-300 px-1.5 py-0.5
                        text-[10px] tabular-nums">
                        {pendingCount}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* 令牌状态栏 */}
      <div className="border-t border-slate-800/80 p-3">
        <button
          onClick={() => setTokenOpen(v => !v)}
          className={`w-full flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs transition
            ${token
              ? 'text-slate-400 hover:bg-slate-800/50'
              : 'bg-amber-500/10 text-amber-300 hover:bg-amber-500/15'}`}
        >
          <span className="relative flex h-2 w-2 shrink-0">
            {!token && (
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full
                bg-amber-400 opacity-75" />
            )}
            <span className={`relative inline-flex h-2 w-2 rounded-full
              ${token ? 'bg-emerald-400' : 'bg-amber-400'}`} />
          </span>
          <span className="flex-1 text-left">{token ? '已连接' : '未配置令牌'}</span>
          <ChevronDown
            size={14} strokeWidth={2}
            className={`transition-transform ${tokenOpen ? 'rotate-180' : ''}`}
          />
        </button>

        <AnimatePresence>
          {tokenOpen && (
            <motion.div
              initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="pt-2">
                <label className="flex items-center gap-1.5 px-0.5 pb-1 text-[10px] text-slate-600">
                  <KeyRound size={11} strokeWidth={2} />
                  ADMIN_TOKEN
                </label>
                <input
                  type="password" value={token} onChange={e => onToken(e.target.value)}
                  placeholder="粘贴管理员令牌"
                  className="w-full rounded-lg bg-slate-900/80 border border-slate-700 px-2.5 py-1.5
                    text-xs outline-none focus:border-sky-500 transition"
                />
                <div className="mt-1 px-0.5 text-[10px] text-slate-600">保存在本地浏览器</div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
