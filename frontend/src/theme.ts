// 分区主题色。每个功能区一个 accent，页面顶部光晕、卡片描边、标题渐变字都跟着它走。
//
// ⚠️ **所有类名必须是完整的字面字符串，绝不允许拼接。**
// Tailwind 3 扫的是源码里出现过的字面量，`bg-${accent}-500` 这种写法扫不到，
// 会被 purge 掉——构建不报错、类型检查也过，只在运行时静默掉色，极难查。
// 所以宁可这张表啰嗦，也不写成 `${a}-500` 的模板串。
//
// 约束：**一页只出一个 accent**。状态色（成功绿、危险红、警告黄）不算 accent，照常用。

export type Accent = 'sky' | 'violet' | 'teal' | 'rose' | 'amber' | 'emerald'

export interface AccentTheme {
  /** 页顶光晕（径向渐变的那团色） */
  glow: string
  /** 区标题的渐变字 */
  title: string
  /** 图标与强调文字 */
  text: string
  /** 次级强调文字，用在数字下方的标签上 */
  textDim: string
  /** 卡片描边 */
  border: string
  /** 浅色底（徽章、选中态） */
  bgSoft: string
  /** 实色按钮 */
  btn: string
  /** 侧栏选中项的左侧指示条 */
  bar: string
  /** 输入框聚焦描边 */
  focus: string
  /** 按钮投影 */
  shadow: string
}

export const ACCENTS: Record<Accent, AccentTheme> = {
  sky: {
    glow: 'from-sky-500/20',
    title: 'from-sky-200 to-sky-400',
    text: 'text-sky-300',
    textDim: 'text-sky-400/70',
    border: 'border-sky-500/30',
    bgSoft: 'bg-sky-500/10',
    btn: 'bg-sky-500 hover:bg-sky-400',
    bar: 'bg-sky-400',
    focus: 'focus:border-sky-500',
    shadow: 'shadow-sky-500/20',
  },
  violet: {
    glow: 'from-violet-500/20',
    title: 'from-violet-200 to-violet-400',
    text: 'text-violet-300',
    textDim: 'text-violet-400/70',
    border: 'border-violet-500/30',
    bgSoft: 'bg-violet-500/10',
    btn: 'bg-violet-500 hover:bg-violet-400',
    bar: 'bg-violet-400',
    focus: 'focus:border-violet-500',
    shadow: 'shadow-violet-500/20',
  },
  teal: {
    glow: 'from-teal-500/20',
    title: 'from-teal-200 to-teal-400',
    text: 'text-teal-300',
    textDim: 'text-teal-400/70',
    border: 'border-teal-500/30',
    bgSoft: 'bg-teal-500/10',
    btn: 'bg-teal-500 hover:bg-teal-400',
    bar: 'bg-teal-400',
    focus: 'focus:border-teal-500',
    shadow: 'shadow-teal-500/20',
  },
  rose: {
    glow: 'from-rose-500/20',
    title: 'from-rose-200 to-rose-400',
    text: 'text-rose-300',
    textDim: 'text-rose-400/70',
    border: 'border-rose-500/30',
    bgSoft: 'bg-rose-500/10',
    btn: 'bg-rose-500 hover:bg-rose-400',
    bar: 'bg-rose-400',
    focus: 'focus:border-rose-500',
    shadow: 'shadow-rose-500/20',
  },
  amber: {
    glow: 'from-amber-500/20',
    title: 'from-amber-200 to-amber-400',
    text: 'text-amber-300',
    textDim: 'text-amber-400/70',
    border: 'border-amber-500/30',
    bgSoft: 'bg-amber-500/10',
    btn: 'bg-amber-500 hover:bg-amber-400',
    bar: 'bg-amber-400',
    focus: 'focus:border-amber-500',
    shadow: 'shadow-amber-500/20',
  },
  emerald: {
    glow: 'from-emerald-500/20',
    title: 'from-emerald-200 to-emerald-400',
    text: 'text-emerald-300',
    textDim: 'text-emerald-400/70',
    border: 'border-emerald-500/30',
    bgSoft: 'bg-emerald-500/10',
    btn: 'bg-emerald-500 hover:bg-emerald-400',
    bar: 'bg-emerald-400',
    focus: 'focus:border-emerald-500',
    shadow: 'shadow-emerald-500/20',
  },
}

/** 分区 id。侧栏导航与主区渲染共用这一套取值。 */
export type SectionId = 'workbench' | 'health' | 'corrections' | 'manage' | 'rules'

/** 每个分区的 accent。工作台同时装着入库（sky）与问答（violet），外壳用 sky。 */
export const SECTION_ACCENT: Record<SectionId, Accent> = {
  workbench: 'sky',
  health: 'teal',
  corrections: 'rose',
  manage: 'amber',
  rules: 'emerald',
}
