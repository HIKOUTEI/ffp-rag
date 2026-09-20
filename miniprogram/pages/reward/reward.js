// 「奖赏」tab 首屏：余额 → 即将到期 → 上限进度 → 本月门槛 → 类别分布 → 期末预计。
//
// 渲染口径全部走 reward-util，**不在 wxml 里做格式化**。
//
// ⚠️ 这一页的核心风险是「把算不出来画成 0」。后端在未登记 / 窗口算不出 / 类别未确认
//    三种情况下一律把 used / pct 置 null（见 summary.py 开头注释），本页必须
//    按 derivation 分三档渲染：正常进度条 / 未登记灰条 / 不可算灰条。
//    分档逻辑集中在 reward-util.capView，页面只负责把它摆出来。
const api = require('../../api')
const u = require('../../reward-util')

// 快照超过这么多天就该重新抄一次了。月结一月一次，给 4 天宽限。
const STALE_DAYS = 35

Page({
  data: {
    loading: true,
    ruleName: {},           // rule_id → 规则原文 note，长按上限行时展示

    // ── 1. 余额卡 ──
    hasBalance: false,      // stock 或 stock.balance 为 null 时 false，整卡换成空状态
    balanceText: '',
    snapshotText: '',       // 「截至 …」，snapshot_at 必须显示，用户要知道这数有多旧
    fromMonthText: '',
    stale: false,           // 超过 STALE_DAYS 没更新 → 出「该抄这个月的数了」按钮

    // ── 2. 即将到期（amount > 0 才有值，否则整块不渲染）──
    expiring: null,

    // ── 3. 上限进度 ──
    caps: [],

    // ── 4. 本月门槛 ──
    thresholds: [],

    // ── 5. 类别分布 ──
    cats: [],
    flowTotalText: '',
    flowRangeText: '',

    // ── 6. 期末预计（projection 为 null 时 proj 也是 null）──
    proj: null,
  },

  onShow() {
    // 自定义 tabBar 必须在每个 tab 页 onShow 里高亮自己，否则切回来是灰的
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setActive('pages/reward/reward')
    }
    // 从录入页 navigateBack 回来也走这里，自动刷新
    this.refresh()
  },

  // 规则集与汇总一起拉。
  // 规则走 ETag + 本地缓存（见 api.reward.rules），二次进入这一页是 304 空体，
  // 拉失败也不阻塞——规则只用来补一句「登记窗口未开」之类的上下文。
  refresh() {
    Promise.all([
      api.reward.rules().catch(() => null),
      api.reward.summary(),
    ])
      .then((r) => this._apply(r[0], r[1]))
      .catch((err) => {
        this.setData({ loading: false })
        this._toast(err)
      })
  },

  _apply(rulePack, s) {
    const rules = (rulePack && rulePack.ruleset && rulePack.ruleset.rules) || []
    const byId = {}
    rules.forEach((r) => { byId[r.id] = r })

    this.setData({
      loading: false,
      ...this._stockView(s.stock),
      caps: (s.caps || []).map((c) => {
        const v = u.capView(c)
        const rule = byId[c.rule_id]
        // 规则本身就还没开（Travel Guru 2026 登记窗口未开）时，灰条的原因
        // 不是「你没填」而是「这规则现在没法用」，要分得清
        v.ruleUnavailable = !!(rule && rule.status === 'unavailable')
        return v
      }),
      thresholds: (s.thresholds || []).map(u.thresholdView),
      ...this._flowView(s.flow),
      proj: this._projView(s.projection),
    })
  },

  // 余额卡。stock 整个为 null（一条月结都没有）或 balance 为 null 时不画大字，
  // 换成空状态——显示一个 0 会让用户以为余额真的是 0。
  _stockView(stock) {
    if (!stock || u.isNil(stock.balance)) {
      return {
        hasBalance: false, balanceText: '', snapshotText: '',
        fromMonthText: '', stale: false, expiring: null,
      }
    }
    const age = u.ageInDays(stock.snapshot_at)
    return {
      hasBalance: true,
      balanceText: u.fmtRC(stock.balance),
      snapshotText: stock.snapshot_at
        ? '截至 ' + u.fmtDate(stock.snapshot_at)
        : '没填截至时间，不知道这个数有多旧',
      fromMonthText: stock.from_month ? u.fmtMonth(stock.from_month) + '月结' : '',
      // 快照日期缺失时无从判断新旧，那本身就该提醒用户去补
      stale: age === null || age > STALE_DAYS,
      expiring: this._expiringView(stock.expiring),
    }
  },

  // 即将到期。amount 为 0 或 null 时返回 null，**整块不渲染**——
  // 「即将到期 $0」是句废话，还会让用户以为系统在提醒什么。
  _expiringView(e) {
    if (!e || u.isNil(e.amount) || Number(e.amount) <= 0) return null
    const left = e.date === null || e.date === undefined ? null : u.daysFromToday(e.date)
    let when = '到期日未填'
    if (e.date) {
      when = u.fmtDate(e.date) + '到期'
      if (left !== null) {
        when += left < 0 ? '（已过期）' : (left === 0 ? '（就是今天）' : '（还有 ' + left + ' 天）')
      }
    }
    return { amountText: u.fmtRC(e.amount), whenText: when, urgent: left !== null && left <= 30 }
  },

  // 类别分布：横向条形。四个类别的饼图读不出差距，所以用条。
  // 条长按最大值归一，不按总额——按总额的话小类别全挤成一根线。
  _flowView(flow) {
    const items = (flow && flow.earned_by_category) || []
    let max = 0
    items.forEach((i) => { if (Number(i.amount) > max) max = Number(i.amount) })
    const range = (flow && flow.range) || {}
    return {
      cats: items.map((i) => ({
        key: i.key,
        name: i.name,
        amountText: u.fmtRC(i.amount),
        // kind==='flat' 是定额收入（迎新、Well+），不参与任何签账额反推
        flat: i.kind === 'flat',
        width: max > 0 ? Math.max(2, Math.round((Number(i.amount) / max) * 100)) + '%' : '0%',
      })),
      flowTotalText: u.fmtRC((flow && flow.total) || 0),
      flowRangeText: range.months
        ? u.fmtMonth(range.from) + ' – ' + u.fmtMonth(range.to) + ' 共 ' + range.months + ' 个月'
        : '',
    }
  },

  // 期末预计。月结不足 2 个完整月时后端给 null，此时显示「再记一个月就能预测」。
  _projView(p) {
    if (!p) return null
    return {
      additionalText: u.fmtRC(p.projected_additional),
      perMonthText: u.fmtRC(p.recurring_per_month),
      windowEndText: p.window_end ? u.fmtDate(p.window_end) : '',
      basisText: p.basis_months + ' 个完整月的均速',
      // 这行必须显示，否则用户会怀疑预测偏低（迎新那 800 被剔掉了）。
      // 为 0 时不显示——没剔掉任何东西，预测也就没被压低，写出来反而是噪音。
      excludedText: !u.isNil(p.excluded_one_off) && Number(p.excluded_one_off) > 0
        ? '已剔除一次性收入 ' + u.fmtRC(p.excluded_one_off)
        : '',
      note: p.note || '',
    }
  },

  // api.js 的 reject 消息本身就是中文用户文案，原样展示
  _toast(err) {
    wx.showToast({ title: (err && err.message) || '加载失败', icon: 'none' })
  },

  // ── 跳转 ──

  onAddMonth() { wx.navigateTo({ url: '/pages/reward-month/reward-month' }) },
  onOpenSettings() { wx.navigateTo({ url: '/pages/reward-settings/reward-settings' }) },
  onOpenSpend() { wx.navigateTo({ url: '/pages/reward-spend/reward-spend' }) },

  // 未登记那一行：直接送去设置页把登记状态填上，不让用户自己找
  onGoEnrol() { this.onOpenSettings() },

  // 定额类别的小标记：长按说明为什么它不参与反推
  onFlatTip() {
    wx.showModal({
      title: '定额收入',
      content: '这个类别的奖赏钱是按笔给的定额（迎新、生日礼遇一类），不是按签账额的百分比。'
        + '除以任何费率都得不到有意义的签账额，所以它不参与上限反推。',
      showCancel: false,
      confirmText: '知道了',
    })
  },
})
