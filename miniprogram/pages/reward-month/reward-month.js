// 月结录入。**这一页的唯一目标是「抄数一分钟内完成」。**
//
// 用户一个月只来一次，抄数超过一分钟下个月就不来了（spec 目标）。
// 所以这里的每一条都是为了省时间，不是为了好看：
//   · 输入框按规则集 categories 的**顺序**排，与 Reward+ App 里的显示顺序一致。
//     顺序错了就没法照抄，一屏的意义全没了。
//   · 类别由后端下发，新增类别不用发版。
//   · 全部 type="digit"，不要让用户在全键盘上找数字。
//   · 已有记录预填旧值——用户是在改，不是重填。
//   · 提交走 PUT，幂等，重复提交安全。
//
// ⚠️ 空输入一律传 null，**不要兜底成 0**。存量三个字段都可空，
//    传 0 会让总览页把「没抄」显示成「余额是 0」。
const api = require('../../api')
const u = require('../../reward-util')

// 字符串 → 数字。空串给 null（不是 0），非数字也给 null。
function toNum(s) {
  const t = String(s === null || s === undefined ? '' : s).trim()
  if (!t) return null
  const n = Number(t)
  return isNaN(n) ? null : n
}

// 数字 → 输入框里的字符串。null 给空串，**不要给 '0'**
function toStr(v) {
  return v === null || v === undefined ? '' : String(v)
}

Page({
  data: {
    loading: true,
    saving: false,

    // ── 月份 ──
    month: '',
    monthText: '',
    monthPickerVisible: false,
    monthEnd: '',           // 选择器上界：不让选未来的月
    existing: false,        // 该月已有记录 → 顶部提示「在改，不是重填」

    // ── 流量：类别输入框，顺序 = 规则集 categories 的顺序 ──
    cats: [],               // [{key, name, kind, flat, value}]

    // ── 存量：三个可空字段 ──
    balance: '',
    expiringAmount: '',
    expiringDate: '',
    datePickerVisible: false,

    // snapshot_at：Reward+ 页面上那个「截至」时间。默认今天，可手改。
    // ⚠️ 后端只收 'YYYY-MM-DD'（DATE_RE 全匹配），不能带时分秒。
    snapshotAt: '',
    snapshotText: '',
    snapshotPickerVisible: false,
  },

  onLoad() {
    const m = u.thisMonth()
    this.setData({ month: m, monthText: u.fmtMonth(m), monthEnd: u.today() })
    Promise.all([
      api.reward.rules(),
      api.reward.listMonths(60),
    ])
      .then((r) => {
        this._months = r[1] || []
        this._categories = (r[0] && r[0].ruleset && r[0].ruleset.categories) || []
        this.setData({ loading: false })
        this._fill(m)
      })
      .catch((err) => {
        this.setData({ loading: false })
        wx.showToast({ title: (err && err.message) || '加载失败', icon: 'none' })
      })
  },

  // 把某月的已有记录填进表单。没有记录就清空（并把 snapshot 重置成今天）。
  _fill(month) {
    const found = (this._months || []).filter((m) => m.month === month)[0] || null
    const flow = (found && found.flow && found.flow.earned) || {}
    const stock = (found && found.stock) || {}
    const expiring = stock.expiring || {}
    const snapshot = found && stock.snapshot_at ? String(stock.snapshot_at).slice(0, 10) : u.today()
    this.setData({
      existing: !!found,
      // 顺序就是 categories 的顺序——与 Reward+ App 里一致，用户才能一路照抄下来
      cats: (this._categories || []).map((c) => ({
        key: c.key,
        name: c.name,
        kind: c.kind,
        flat: c.kind === 'flat',
        value: toStr(flow[c.key]),
      })),
      balance: toStr(stock.balance),
      expiringAmount: toStr(expiring.amount),
      expiringDate: expiring.date || '',
      snapshotAt: snapshot,
      snapshotText: u.fmtDate(snapshot),
    })
  },

  // ── 月份 ──

  openMonthPicker() { this.setData({ monthPickerVisible: true }) },
  onMonthCancel() { this.setData({ monthPickerVisible: false }) },
  onMonthConfirm(e) {
    const month = e.detail.value      // format 已指定为 YYYY-MM
    this.setData({ monthPickerVisible: false, month, monthText: u.fmtMonth(month) })
    this._fill(month)
  },

  // ── 输入 ──

  onCatInput(e) {
    this.setData({ ['cats[' + e.currentTarget.dataset.i + '].value']: e.detail.value || '' })
  },
  onBalanceInput(e) { this.setData({ balance: e.detail.value || '' }) },
  onExpiringInput(e) { this.setData({ expiringAmount: e.detail.value || '' }) },

  openDatePicker() { this.setData({ datePickerVisible: true }) },
  onDateCancel() { this.setData({ datePickerVisible: false }) },
  onDateConfirm(e) { this.setData({ datePickerVisible: false, expiringDate: e.detail.value }) },
  onClearExpiringDate() { this.setData({ expiringDate: '' }) },

  openSnapshotPicker() { this.setData({ snapshotPickerVisible: true }) },
  onSnapshotCancel() { this.setData({ snapshotPickerVisible: false }) },
  onSnapshotConfirm(e) {
    const d = e.detail.value
    this.setData({ snapshotPickerVisible: false, snapshotAt: d, snapshotText: u.fmtDate(d) })
  },

  // ── 提交 ──

  onSave() {
    if (this.data.saving) return
    const earned = {}
    this.data.cats.forEach((c) => {
      const v = toNum(c.value)
      // 没填的类别不进 earned：传 0 和不传在汇总上等价，但不传更诚实
      if (v !== null) earned[c.key] = v
    })

    const expAmount = toNum(this.data.expiringAmount)
    const body = {
      flow: { earned },
      stock: {
        // 三个都可空。**空就是 null，不是 0**
        balance: toNum(this.data.balance),
        expiring: { amount: expAmount, date: this.data.expiringDate || null },
        snapshot_at: this.data.snapshotAt || null,
      },
    }

    this.setData({ saving: true })
    // PUT 幂等：同一个月反复提交，库里始终只有一条
    api.reward.putMonth(this.data.month, body)
      .then(() => {
        this.setData({ saving: false })
        wx.showToast({ title: '已保存' })
        // 总览页 onShow 会自己刷新，不需要事件总线
        setTimeout(() => wx.navigateBack(), 600)
      })
      .catch((err) => {
        this.setData({ saving: false })
        // 后端 detail 已是中文用户文案（如「未知的奖赏类别：xx（规则集第 3 版）。」），原样展示
        wx.showToast({ title: (err && err.message) || '保存失败', icon: 'none' })
      })
  },
})
