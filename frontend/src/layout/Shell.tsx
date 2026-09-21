// 外壳：侧栏 + 主区骨架 + 分区光晕。
//
// 窄屏（<lg）侧栏收成抽屉。抽屉开合是纯 UI 状态，留在本组件内。
import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Menu, X } from 'lucide-react'
import { Sidebar, type TokenState } from './Sidebar'
import { ACCENTS, SECTION_ACCENT, type SectionId } from '../theme'

export function Shell({
  section, onSection, pendingCount, token, onToken, tokenState, tokenError,
  banner, children,
}: {
  section: SectionId
  onSection: (s: SectionId) => void
  pendingCount: number
  token: string
  onToken: (t: string) => void
  tokenState: TokenState
  tokenError: string
  /** 全局提示条（原 msg），跟着主区走，切页不影响 */
  banner?: React.ReactNode
  children: React.ReactNode
}) {
  const [drawer, setDrawer] = useState(false)
  const t = ACCENTS[SECTION_ACCENT[section]]

  function go(s: SectionId) {
    onSection(s)
    setDrawer(false)
  }

  return (
    <div className="min-h-full bg-gradient-to-br from-[#0b1020] via-[#0d1226] to-[#131a35] text-slate-100">
      {/* 桌面侧栏 */}
      <aside className="hidden lg:block fixed inset-y-0 left-0 w-60 border-r border-slate-800/80 z-30">
        <Sidebar
          section={section} onSection={go} pendingCount={pendingCount}
          token={token} onToken={onToken}
          tokenState={tokenState} tokenError={tokenError}
        />
      </aside>

      {/* 窄屏抽屉 */}
      <AnimatePresence>
        {drawer && (
          <>
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              onClick={() => setDrawer(false)}
              className="lg:hidden fixed inset-0 bg-black/60 backdrop-blur-sm z-40"
            />
            <motion.aside
              initial={{ x: -260 }} animate={{ x: 0 }} exit={{ x: -260 }}
              transition={{ type: 'tween', duration: 0.2 }}
              className="lg:hidden fixed inset-y-0 left-0 w-60 border-r border-slate-800 z-50"
            >
              <Sidebar
                section={section} onSection={go} pendingCount={pendingCount}
                token={token} onToken={onToken}
                tokenState={tokenState} tokenError={tokenError}
              />
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      <div className="lg:pl-60">
        <div className="relative overflow-hidden min-h-screen">
          {/* 分区光晕：整块主区顶部洒下来的一层同色光，切区时淡入淡出 */}
          <AnimatePresence mode="wait">
            <motion.div
              key={section}
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              transition={{ duration: 0.4 }}
              className="pointer-events-none absolute inset-x-0 top-0 h-80"
            >
              <div className={`absolute inset-x-0 top-0 h-64 bg-gradient-to-b ${t.glow} to-transparent`} />
              <div className={`absolute -top-24 left-1/3 h-64 w-[40rem] -translate-x-1/2 rounded-full
                blur-3xl bg-gradient-to-r ${t.glow} to-transparent`} />
            </motion.div>
          </AnimatePresence>

          {/* 窄屏顶栏 */}
          <div className="lg:hidden relative z-10 flex items-center gap-3 px-4 py-3
            border-b border-slate-800/60">
            <button
              onClick={() => setDrawer(true)}
              className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800/60 hover:text-slate-200 transition"
            >
              {drawer ? <X size={18} /> : <Menu size={18} />}
            </button>
            <span className="text-sm font-semibold bg-gradient-to-r from-sky-300 to-violet-300
              bg-clip-text text-transparent">
              ffp-rag
            </span>
          </div>

          <main className="relative z-10 mx-auto max-w-7xl px-5 lg:px-8 py-8 lg:py-10">
            {banner}
            <AnimatePresence mode="wait">
              <motion.div
                key={section}
                initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.2 }}
              >
                {children}
              </motion.div>
            </AnimatePresence>
          </main>
        </div>
      </div>
    </div>
  )
}
