// 「奖赏」四个页面共用的纯函数：金额格式化、周期窗口文案、进度渲染档位。
// 放这里是为了口径一致——同一条上限在总览页与设置页必须长得一样。
//
// ⚠️ 本文件最重要的一条：**null 不是 0**。
// 后端在「算不出来」时一律给 null（见 backend/app/rewardcash/summary.py 的开头注释），
// 任何把 null 兜底成 0 的写法都会画出一条空进度条，等于告诉用户
// 「你还没开始用这个额度」——那是个比不显示危险得多的谎。
// 所以下面的 fmt* 遇到 null 返回破折号，barWidth/fmtPct 遇到 null 返回 null，
// 调用方必须据此走灰条那条分支。

function pad(n) {
  return n < 10 ? '0' + n : '' + n
}

// 今天，'YYYY-MM-DD'
function today() {
  const d = new Date()
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
}

// 当前月，'YYYY-MM'
function thisMonth() {
  const d = new Date()
  return d.getFullYear() + '-' + pad(d.getMonth() + 1)
}

// ===== 金额 =====

// 千分位，最多两位小数。3023 → '3,023'；64950.5 → '64,950.5'
function group(v) {
  const n = Math.round(Number(v) * 100) / 100
  if (isNaN(n)) return '—'
  const abs = Math.abs(n)
  const int = Math.floor(abs)
  const frac = Math.round((abs - int) * 100)
  let s = String(int).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  if (frac) s += '.' + (frac % 10 === 0 ? frac / 10 : (frac < 10 ? '0' + frac : frac))
  return (n < 0 ? '-' : '') + s
}

function isNil(v) {
  return v === null || v === undefined || v === ''
}

// 奖赏钱。$1 RC = HK$1，写成 '$3,023'
function fmtRC(v) {
  return isNil(v) ? '—' : '$' + group(v)
}

// 港币签账额
function fmtHKD(v) {
  return isNil(v) ? '—' : 'HK$' + group(v)
}

// 按上限口径选单位。cap.kind='spend' 限的是签账港币额，'reward' 限的是拿到的 RC，
// **二者不可混算**，所以单位也必须跟着 kind 走，不能统一写 $。
function fmtByCapKind(v, capKind) {
  return capKind === 'spend' ? fmtHKD(v) : fmtRC(v)
}

// ===== 日期 =====

// 'YYYY-MM-DD' 或 '2026-09-19T22:46:00+08:00' → [y, m, d]，取不到返回 null。
// 只认前 10 个字符，**不走 new Date(str)**：iOS 对带时区 ISO 串的解析口径不一，
// 而这里只需要「哪一天」，日级精度足够。
function dateParts(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s === null || s === undefined ? '' : s))
  return m ? [+m[1], +m[2], +m[3]] : null
}

// 自 1970 起的天数。解析不了返回 null
function dayNumber(s) {
  const p = dateParts(s)
  return p ? Math.round(Date.UTC(p[0], p[1] - 1, p[2]) / 86400000) : null
}

// b - a，相差几天。任一解析不了返回 null（不是 0）
function daysBetween(a, b) {
  const x = dayNumber(a)
  const y = dayNumber(b)
  return x === null || y === null ? null : y - x
}

// 距今天还有几天。正数=未来，负数=已过
function daysFromToday(s) {
  return daysBetween(today(), s)
}

// 这个快照有多旧（天）。解析不了返回 null
function ageInDays(s) {
  const d = daysFromToday(s)
  return d === null ? null : -d
}

// '2026-09-19' → '9月19日'；非今年带年份。
// 不复用 rail-util.fmtDate：那个按 '-' 硬切三段，喂进带时分秒的 snapshot_at 会切歪。
function fmtDate(s) {
  const p = dateParts(s)
  if (!p) return ''
  const md = p[1] + '月' + p[2] + '日'
  return p[0] === new Date().getFullYear() ? md : p[0] + '年' + md
}

// '2026-09' → '2026 年 9 月'
function fmtMonth(m) {
  const g = /^(\d{4})-(\d{2})$/.exec(String(m || ''))
  return g ? +g[1] + ' 年 ' + +g[2] + ' 月' : String(m || '')
}

// ===== 周期窗口 =====

const PERIOD_LABEL = {
  calendar_year: '历年',
  calendar_month: '历月',
  promo_period: '促销期',
  membership_year: '会籍年',
}

// 周期窗口文案。**一律照后端给的 window 渲染，绝不内联日期**——
// 历年与本期促销恰好都在 12-31 结束，写死现在全对、跨到 2027-01 全错。
// window 为 null（会籍年缺起算日 / promo 缺起止）时只给口径名。
function fmtWindow(period, window) {
  const label = PERIOD_LABEL[period] || ''
  if (!window || !window.start || !window.end) return label
  const s = dateParts(window.start)
  if (s && period === 'calendar_year') return s[0] + ' 年'
  if (s && period === 'calendar_month') return s[0] + ' 年 ' + s[1] + ' 月'
  return label + ' ' + fmtDate(window.start) + '–' + fmtDate(window.end)
}

// 窗口还剩几天。window 缺失或已过期返回 null
function daysLeftIn(window) {
  if (!window || !window.end) return null
  const d = daysFromToday(window.end)
  return d === null || d < 0 ? null : d
}

// 「还剩 N 天」。算不出来返回空串，不显示「还剩 0 天」那种歧义文案
function fmtDaysLeft(window) {
  const d = daysLeftIn(window)
  if (d === null) return ''
  return d === 0 ? '今天最后一天' : '还剩 ' + d + ' 天'
}

// ===== 进度 =====

// pct 是 0~1 的小数（后端已 min 到 1.0）。**只接受数字**——
// null 进来就 null 出去，调用方必须据此走灰条分支，不许兜底成 0。
function barWidth(pct) {
  if (isNil(pct) || isNaN(Number(pct))) return null
  const p = Math.max(0, Math.min(1, Number(pct)))
  // 极小的非零值给 2% 的视觉厚度，否则「用了一点点」和「一点没用」看着一样
  if (p > 0 && p < 0.02) return '2%'
  return Math.round(p * 100) + '%'
}

function fmtPct(pct) {
  if (isNil(pct) || isNaN(Number(pct))) return null
  return Math.round(Number(pct) * 100) + '%'
}

// ===== 视图模型 =====

// 一条上限 → 视图模型。**四种 derivation 三种渲染，绝不共用一套：**
//
//   rc_backsolve / spend_entries → mode 'progress'：正常进度条 + 数字
//   not_enrolled                 → mode 'blocked' ：灰条 +「未登记，签账不计入」+ 去登记
//   unavailable                  → mode 'unknown' ：灰条 + derivation_note
//
// used == null 时即便 derivation 写着 rc_backsolve 也一律降级到 'unknown'——
// 这一层兜底是为了「后端哪天漏置了 derivation」时页面仍然不会画出 0%。
function capView(c) {
  const known = (c.derivation === 'rc_backsolve' || c.derivation === 'spend_entries')
    && !isNil(c.used)
  const mode = c.derivation === 'not_enrolled' ? 'blocked' : (known ? 'progress' : 'unknown')
  const cap = c.cap || {}
  const isSpend = cap.kind === 'spend'
  return {
    ruleId: c.rule_id,
    ruleName: c.rule_name,
    mode,
    // 下面四个只在 progress 档有值；其余档一律 null，wxml 里整段不渲染
    barWidth: mode === 'progress' ? barWidth(c.pct) : null,
    pctText: mode === 'progress' ? fmtPct(c.pct) : null,
    usedText: mode === 'progress'
      ? fmtByCapKind(c.used, cap.kind) + ' / ' + fmtByCapKind(cap.amount, cap.kind)
      : null,
    remainingText: mode === 'progress'
      ? '还可' + (isSpend ? '刷 ' : '赚 ') + fmtByCapKind(c.remaining, cap.kind)
      : null,
    // 灰条档也要让用户知道这条上限本身是多少，否则整行只剩一句「算不出来」
    capText: fmtByCapKind(cap.amount, cap.kind) + (isSpend ? ' 签账' : ' 奖赏'),
    windowText: fmtWindow(cap.period, c.window),
    daysLeftText: fmtDaysLeft(c.window),
    note: c.derivation_note || '',
  }
}

// 一条门槛 → 视图模型。门槛只能靠逐笔签账算（月结次月才抄，那时周期已结束），
// 所以没有逐笔记录时是 'unknown'，文案要把「去记几笔」这条路指出来。
function thresholdView(t) {
  const known = t.derivation === 'spend_entries' && !isNil(t.current)
  const mode = !known ? 'unknown' : (t.met === true ? 'met' : 'short')
  return {
    ruleId: t.rule_id,
    ruleName: t.rule_name,
    requirement: t.requirement || '',
    mode,
    currentText: known ? fmtHKD(t.current) : null,
    shortText: mode === 'short' ? '还差 ' + fmtHKD(t.remaining) : null,
    daysLeftText: fmtDaysLeft(t.window),
    windowText: fmtWindow('calendar_month', t.window),
    note: t.derivation_note || '',
  }
}

module.exports = {
  today, thisMonth,
  group, fmtRC, fmtHKD, fmtByCapKind, isNil,
  dateParts, daysBetween, daysFromToday, ageInDays, fmtDate, fmtMonth,
  fmtWindow, daysLeftIn, fmtDaysLeft,
  barWidth, fmtPct,
  capView, thresholdView,
}
