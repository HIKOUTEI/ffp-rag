// 逐笔签账录入。**摆明是可选功能**——入口只在总览页门槛那一行和一个次级入口，
// 不做首屏大按钮。它唯一不可替代的用途是月中推算门槛进度：月结是次月才抄的，
// 那时门槛周期已经结束（ADR-0010）。
//
// 两个容易白丢钱的地方，文案必须写清楚，不能只给一个开关：
//   · DCC：刷卡时被问「港币还是人民币」，选了港币就同时失去扫码 +2% 和 Travel Guru +6%。
//   · 付法：AlipayHK / 微信支付 / 网上 都只有基本 0.4%，不在「二维码支付」定义内。
const api = require('../../api')
const u = require('../../reward-util')

// 取值必须与 backend/app/rewardcash/schemas.py 的 Literal 一致，写错会 422。
const REGIONS = [
  { value: 'mainland', label: '内地' },
  { value: 'macau', label: '澳门' },
  { value: 'hongkong', label: '香港' },
  { value: 'overseas', label: '海外' },
]

const MERCHANTS = [
  { value: 'dining', label: '餐饮' },
  { value: 'other', label: '其他' },
]

// 币种：后端不接汇率服务，人民币／澳门币按 1:1 预填港币额（迎新条款本身就按 1:1）。
const CURRENCIES = [
  { value: 'CNY', label: '人民币', oneToOne: true },
  { value: 'MOP', label: '澳门币', oneToOne: true },
  { value: 'HKD', label: '港币', oneToOne: true },
  { value: 'OTHER', label: '其他', oneToOne: false },
]

const CHANNELS = [
  { value: 'rewardplus_qr', label: 'Reward+ 扫码（仅主卡）', sub: '' },
  { value: 'unionpay_qr', label: '云闪付扫码', sub: '' },
  { value: 'mobile_pay', label: 'Apple / Google / Samsung Pay', sub: '' },
  { value: 'physical_card', label: '实体卡', sub: '' },
  { value: 'alipayhk', label: 'AlipayHK', sub: '只有基本 0.4%' },
  { value: 'wechat', label: '微信支付', sub: '只有基本 0.4%' },
  { value: 'online', label: '网上', sub: '只有基本 0.4%' },
  { value: 'other', label: '其他', sub: '' },
]

function labelOf(list, value) {
  const hit = list.filter((i) => i.value === value)[0]
  return hit ? hit.label : value
}

function toNum(s) {
  const t = String(s === null || s === undefined ? '' : s).trim()
  if (!t) return null
  const n = Number(t)
  return isNaN(n) ? null : n
}

Page({
  data: {
    regions: REGIONS,
    merchants: MERCHANTS,
    currencies: CURRENCIES,
    channels: CHANNELS,

    // ── 表单 ──
    spendDate: '',
    dateText: '',
    datePickerVisible: false,
    amount: '',
    currency: 'CNY',
    amountHkd: '',
    hkdTouched: false,      // 用户手改过港币额就不再自动覆盖
    showHkdHint: true,      // 1:1 预填的说明，只在可 1:1 的币种下显示
    region: 'mainland',
    merchantCategory: 'other',
    channel: 'rewardplus_qr',
    settledHkd: false,
    note: '',
    saving: false,

    // ── 列表 ──
    loading: true,
    spends: [],
  },

  onLoad() {
    const d = u.today()
    this.setData({ spendDate: d, dateText: u.fmtDate(d) })
    this.refresh()
  },

  refresh() {
    api.reward.listSpends({ limit: 200 })
      .then((list) => this.setData({ loading: false, spends: list.map(this._toView) }))
      .catch((err) => {
        this.setData({ loading: false })
        wx.showToast({ title: (err && err.message) || '加载失败', icon: 'none' })
      })
  },

  _toView(s) {
    return {
      id: s.id,
      dateText: u.fmtDate(s.spend_date),
      // 原币与港币都显示：折算是用户填的，得让他能核对
      amountText: s.currency + ' ' + u.group(s.amount),
      hkdText: u.fmtHKD(s.amount_hkd),
      regionText: labelOf(REGIONS, s.region),
      merchantText: labelOf(MERCHANTS, s.merchant_category),
      channelText: labelOf(CHANNELS, s.channel),
      // 被 DCC 成港币：这笔基本吃不到加成，列表里要一眼看得见
      dcc: s.settled_hkd === true,
      note: s.note || '',
    }
  },

  // ── 表单 ──

  openDatePicker() { this.setData({ datePickerVisible: true }) },
  onDateCancel() { this.setData({ datePickerVisible: false }) },
  onDateConfirm(e) {
    const d = e.detail.value
    this.setData({ datePickerVisible: false, spendDate: d, dateText: u.fmtDate(d) })
  },

  onAmountInput(e) {
    const v = e.detail.value || ''
    const patch = { amount: v }
    // 人民币／澳门币／港币按 1:1 预填港币额，用户改过就不再覆盖
    if (!this.data.hkdTouched && this._oneToOne(this.data.currency)) patch.amountHkd = v
    this.setData(patch)
  },

  onHkdInput(e) {
    this.setData({ amountHkd: e.detail.value || '', hkdTouched: true })
  },

  onPickCurrency(e) {
    const currency = e.currentTarget.dataset.value
    const patch = { currency, showHkdHint: this._oneToOne(currency) }
    if (!this.data.hkdTouched && this._oneToOne(currency)) patch.amountHkd = this.data.amount
    this.setData(patch)
  },

  _oneToOne(currency) {
    const hit = CURRENCIES.filter((c) => c.value === currency)[0]
    return !!(hit && hit.oneToOne)
  },

  onPickRegion(e) { this.setData({ region: e.currentTarget.dataset.value }) },
  onPickMerchant(e) { this.setData({ merchantCategory: e.currentTarget.dataset.value }) },
  onPickChannel(e) { this.setData({ channel: e.currentTarget.dataset.value }) },
  onToggleDcc(e) { this.setData({ settledHkd: !!e.detail.value }) },
  onNoteInput(e) { this.setData({ note: e.detail.value || '' }) },

  // DCC 那个开关旁边的问号：整套规则里最容易白丢钱的地方
  onDccTip() {
    wx.showModal({
      title: '什么是 DCC',
      content: '刷卡或扫码时，终端有时会问你「用港币还是人民币结算」。选了港币就是 DCC。'
        + '这一笔会同时失去内地／澳门扫码的 +2% 和 Travel Guru 的 +6%，汇率还更差。'
        + '正确做法是永远选当地货币。',
      showCancel: false,
      confirmText: '知道了',
    })
  },

  // ── 提交 ──

  onSave() {
    if (this.data.saving) return
    const amount = toNum(this.data.amount)
    const amountHkd = toNum(this.data.amountHkd)
    if (amount === null) {
      wx.showToast({ title: '请填写金额', icon: 'none' })
      return
    }
    // amount_hkd 必填且不能为负（后端会 422）。先在这里拦一道，省一次往返。
    if (amountHkd === null) {
      wx.showToast({ title: '请填写折合港币金额', icon: 'none' })
      return
    }
    if (amountHkd < 0) {
      wx.showToast({ title: '港币金额不能为负', icon: 'none' })
      return
    }

    this.setData({ saving: true })
    api.reward.createSpend({
      spend_date: this.data.spendDate,
      amount,
      currency: this.data.currency,
      amount_hkd: amountHkd,
      region: this.data.region,
      merchant_category: this.data.merchantCategory,
      channel: this.data.channel,
      settled_hkd: this.data.settledHkd,
      card: null,
      note: this.data.note || null,
    })
      .then(() => {
        // 只清金额与备注：地区／付法／币种多半连着记几笔都一样，清掉等于让用户重选
        this.setData({
          saving: false, amount: '', amountHkd: '', hkdTouched: false, note: '',
        })
        wx.showToast({ title: '已记录' })
        this.refresh()
      })
      .catch((err) => {
        this.setData({ saving: false })
        wx.showToast({ title: (err && err.message) || '保存失败', icon: 'none' })
      })
  },

  onDelete(e) {
    const id = e.currentTarget.dataset.id
    const item = this.data.spends.filter((s) => s.id === id)[0]
    if (!item) return
    wx.showModal({
      title: '删除这笔签账？',
      content: item.dateText + ' · ' + item.hkdText,
      confirmColor: '#ff3b30',
      success: (r) => {
        if (!r.confirm) return
        api.reward.deleteSpend(id)
          .then(() => {
            wx.showToast({ title: '已删除', icon: 'none' })
            this.refresh()
          })
          .catch((err) => wx.showToast({ title: (err && err.message) || '删除失败', icon: 'none' }))
      },
    })
  },
})
