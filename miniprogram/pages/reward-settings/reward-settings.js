// 登记状态与设置。不单开 tab，入口在总览页余额卡右上角的齿轮 + 次级入口列表。
//
// ⚠️ 登记状态是**三态**，不是开关：
//     没问过（key 不存在） / 确认未登记（null） / 已登记（有日期）
//   压成两态就分不清「用户说没登记」和「我们还没问过」——前者可以放心显示
//   「未登记，签账不计入」，后者显示同一句话就是在瞎猜。
//   登记日期本身也有用：登记前的签账一分不补算。
//
// PUT /rewardcash/settings 是**整份覆盖**，所以提交时必须回传完整的 enrolled 字典，
// 不能只传改动的那一条。
const api = require('../../api')
const u = require('../../reward-util')

// 三态在 UI 上的三个选项。value 与提交时的取值一一对应，见 _buildEnrolled。
const STATES = [
  { value: 'unknown', label: '还没确认' },
  { value: 'no', label: '未登记' },
  { value: 'yes', label: '已登记' },
]

const TIERS = [
  { value: 'go', label: 'GO', sub: '+3% · 600 RC' },
  { value: 'ging', label: 'GING', sub: '+4% · 1,400 RC' },
  { value: 'guru', label: 'GURU', sub: '+6% · 2,200 RC' },
]

Page({
  data: {
    loading: true,
    saving: false,
    states: STATES,
    tiers: TIERS,

    // 需要登记的规则。[{id, name, state, date, dateText, disabled, hint}]
    rows: [],

    // ── Travel Guru 会籍年 ──
    // 会籍年起算日是 cap.period === 'membership_year' 唯一的起算依据，不填那条上限算不出来。
    showGuru: false,
    guruDisabled: false,
    guruHint: '',
    membershipStart: '',
    membershipText: '',
    guruTier: '',

    datePickerVisible: false,
    pickingIndex: -1,       // -1 表示在选会籍年起算日，否则是 rows 的下标
    pickerValue: '',        // 打开时喂给选择器的初值，空串时它自己落到今天
  },

  onLoad() {
    Promise.all([api.reward.rules(), api.reward.settings()])
      .then((r) => this._apply(r[0], r[1]))
      .catch((err) => {
        this.setData({ loading: false })
        wx.showToast({ title: (err && err.message) || '加载失败', icon: 'none' })
      })
  },

  _apply(rulePack, settings) {
    const rules = (rulePack && rulePack.ruleset && rulePack.ruleset.rules) || []
    const enrolled = (settings && settings.enrolled) || {}

    const rows = rules
      .filter((r) => r.requires_enrolment)
      .map((r) => {
        // 三态还原：key 不存在 → unknown；值为 null → no；有日期 → yes
        const has = Object.prototype.hasOwnProperty.call(enrolled, r.id)
        const date = has && enrolled[r.id] ? String(enrolled[r.id]) : ''
        return {
          id: r.id,
          name: r.name,
          state: !has ? 'unknown' : (date ? 'yes' : 'no'),
          date,
          dateText: date ? u.fmtDate(date) : '未填',
          // 规则本身还没开放登记时不让用户乱标——标了也没用，还会误导上限进度
          disabled: r.status === 'unavailable',
          hint: r.status === 'unavailable' ? '该规则目前未开放登记。' : '',
        }
      })

    // 会籍年那块跟着「有没有 membership_year 上限」走，不写死 rule id：
    // 将来 Travel Guru 拆成三条规则时这里不用改。
    const guruRule = rules.filter(
      (r) => (r.caps || []).filter((c) => c.period === 'membership_year').length > 0
    )[0] || null
    const start = (settings && settings.membership_year_start) || ''

    this.setData({
      loading: false,
      rows,
      showGuru: !!guruRule,
      guruDisabled: !!(guruRule && guruRule.status === 'unavailable'),
      guruHint: guruRule && guruRule.status === 'unavailable'
        ? '登记窗口未开，这一块暂时填了也用不上。'
        : '',
      membershipStart: start,
      membershipText: start ? u.fmtDate(start) : '未填',
      guruTier: (settings && settings.travel_guru_tier) || '',
    })
  },

  // ── 三态 ──

  onPickState(e) {
    const i = Number(e.currentTarget.dataset.i)
    const state = e.currentTarget.dataset.value
    if (this.data.rows[i].disabled) return
    const patch = { ['rows[' + i + '].state']: state }
    // 从「已登记」退回去时把日期一并清掉，免得下次又被当成已登记提交
    if (state !== 'yes') {
      patch['rows[' + i + '].date'] = ''
      patch['rows[' + i + '].dateText'] = '未填'
    }
    this.setData(patch)
  },

  openRowDate(e) {
    const i = Number(e.currentTarget.dataset.i)
    if (this.data.rows[i].disabled) return
    this.setData({
      pickingIndex: i,
      pickerValue: this.data.rows[i].date || u.today(),
      datePickerVisible: true,
    })
  },

  openMembershipDate() {
    if (this.data.guruDisabled) return
    this.setData({
      pickingIndex: -1,
      pickerValue: this.data.membershipStart || u.today(),
      datePickerVisible: true,
    })
  },

  onDateCancel() { this.setData({ datePickerVisible: false }) },

  onDateConfirm(e) {
    const d = e.detail.value
    const i = this.data.pickingIndex
    if (i < 0) {
      this.setData({ datePickerVisible: false, membershipStart: d, membershipText: u.fmtDate(d) })
      return
    }
    this.setData({
      datePickerVisible: false,
      ['rows[' + i + '].date']: d,
      ['rows[' + i + '].dateText']: u.fmtDate(d),
    })
  },

  onPickTier(e) {
    if (this.data.guruDisabled) return
    this.setData({ guruTier: e.currentTarget.dataset.value })
  },

  // ── 提交 ──

  // 三态 → enrolled 字典。**必须回传完整那一份**，PUT 是整份覆盖。
  //   yes  → 日期字符串
  //   no   → null（确认未登记）
  //   unknown → 不写这个 key（没问过）
  _buildEnrolled() {
    const enrolled = {}
    this.data.rows.forEach((r) => {
      if (r.state === 'yes') enrolled[r.id] = r.date
      else if (r.state === 'no') enrolled[r.id] = null
    })
    return enrolled
  },

  onSave() {
    if (this.data.saving) return
    // 选了「已登记」却没填日期时必须拦住：写成 null 会被后端读成「确认未登记」，
    // 语义直接翻转，上限进度会莫名其妙地变成灰条。
    const bad = this.data.rows.filter((r) => r.state === 'yes' && !r.date)[0]
    if (bad) {
      wx.showToast({ title: '请填写「' + bad.name + '」的登记日期', icon: 'none' })
      return
    }

    this.setData({ saving: true })
    api.reward.putSettings({
      enrolled: this._buildEnrolled(),
      membership_year_start: this.data.membershipStart || null,
      travel_guru_tier: this.data.guruTier || null,
    })
      .then(() => {
        this.setData({ saving: false })
        wx.showToast({ title: '已保存' })
        setTimeout(() => wx.navigateBack(), 600)
      })
      .catch((err) => {
        this.setData({ saving: false })
        wx.showToast({ title: (err && err.message) || '保存失败', icon: 'none' })
      })
  },

  // ── 数据清理 ──
  // 奖赏钱余额与签账记录属个人财务信息，得有个就地清掉的入口（spec「上线前必办」）。
  // 与「注销账号」不同：那个是销号，这个只清账本，账号还在。
  onClearData() {
    wx.showModal({
      title: '清空奖赏钱数据？',
      content: '你的全部月结记录、逐笔签账与登记设置将被删除，不可恢复。账号本身保留。',
      confirmColor: '#ff3b30',
      success: (r) => {
        if (!r.confirm) return
        api.reward.clearData()
          .then((res) => {
            wx.showToast({
              title: '已清空 ' + ((res && res.months) || 0) + ' 个月结', icon: 'none',
            })
            setTimeout(() => wx.navigateBack(), 800)
          })
          .catch((err) => wx.showToast({ title: (err && err.message) || '清空失败', icon: 'none' }))
      },
    })
  },
})
