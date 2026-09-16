const { AIRLINES, HOTELS, CARDS, POINT_SYSTEMS, OTHER } = require('../../catalog')

const STORE_KEY = 'ffp_user_profile'

// 每类的元信息：品牌表、标识号字段名、文案
const TYPES = {
  airline: { title: '航司会籍', emoji: '✈️', brands: AIRLINES, brandLabel: '航司', idLabel: '会员卡号',
    emptyHint: '还没有航司会籍，点右上角 + 添加' },
  hotel:   { title: '酒店会籍', emoji: '🏨', brands: HOTELS, brandLabel: '酒店集团', idLabel: '会员号',
    emptyHint: '还没有酒店会籍，点右上角 + 添加' },
  card:    { title: '信用卡', emoji: '💳', brands: CARDS, brandLabel: '发卡行', idLabel: '',
    emptyHint: '还没有信用卡，点右上角 + 添加' },
}

const toOptions = (arr) => arr.map((s) => ({ label: s, value: s }))

Page({
  data: {
    sections: [],           // 渲染用：[{type,title,emoji,entries,emptyHint}]
    otherLabel: OTHER,

    // 表单
    formVisible: false,
    editing: false,
    curType: 'airline',
    formTitle: '',
    brandLabel: '品牌',
    idLabel: '标识号',
    isCard: false,
    form: { id: '', brand: '', brandOther: '', tier: '', idno: '', points: '' },
    canSave: false,

    // picker
    brandPickerVisible: false, brandOptions: [], brandPickerValue: [],
    tierPickerVisible: false, tierOptions: [], tierPickerValue: [],
    pointsPickerVisible: false, pointsOptions: toOptions(POINT_SYSTEMS), pointsPickerValue: [],
  },

  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setActive('pages/profile/profile')
    }
    this.refresh()
  },

  // 从 Storage 读并组织成分区渲染结构
  refresh() {
    const store = wx.getStorageSync(STORE_KEY) || { airline: [], hotel: [], card: [] }
    const sections = Object.keys(TYPES).map((type) => {
      const meta = TYPES[type]
      const entries = (store[type] || []).map((e) => ({
        ...e,
        extra: this._extraText(type, e),
      }))
      return { type, title: meta.title, emoji: meta.emoji, entries, emptyHint: meta.emptyHint }
    })
    this.setData({ sections })
    this._store = store
  },

  _extraText(type, e) {
    if (type === 'card') return e.points ? '积分：' + e.points : ''
    return e.idno ? TYPES[type].idLabel + '：' + e.idno : ''
  },

  // ── 新增 ──
  onAdd(e) {
    const type = e.currentTarget.dataset.type
    const meta = TYPES[type]
    this.setData({
      formVisible: true, editing: false, curType: type,
      formTitle: meta.title, brandLabel: meta.brandLabel, idLabel: meta.idLabel,
      isCard: type === 'card',
      form: { id: '', brand: '', brandOther: '', tier: '', idno: '', points: '' },
      canSave: false,
    })
  },

  // ── 编辑 ──
  onEdit(e) {
    const { type, id } = e.currentTarget.dataset
    const meta = TYPES[type]
    const entry = (this._store[type] || []).find((x) => x.id === id)
    if (!entry) return
    // 如果 brand 不在预置表里，说明是「其他」自定义
    const known = Object.keys(meta.brands).includes(entry.brand)
    this.setData({
      formVisible: true, editing: true, curType: type,
      formTitle: meta.title, brandLabel: meta.brandLabel, idLabel: meta.idLabel,
      isCard: type === 'card',
      form: {
        id: entry.id,
        brand: known ? entry.brand : OTHER,
        brandOther: known ? '' : entry.brand,
        tier: entry.tier || '',
        idno: entry.idno || '',
        points: entry.points || '',
      },
    }, () => this._recheck())
  },

  // ── 删除 ──
  onDelete(e) {
    const { type, id } = e.currentTarget.dataset
    wx.showModal({
      title: '删除', content: '确定删除这一项？',
      success: (r) => {
        if (!r.confirm) return
        this._store[type] = (this._store[type] || []).filter((x) => x.id !== id)
        wx.setStorageSync(STORE_KEY, this._store)
        this.refresh()
      },
    })
  },

  // ── 品牌 picker ──
  openBrandPicker() {
    const brands = Object.keys(TYPES[this.data.curType].brands)
    this.setData({
      brandOptions: toOptions(brands),
      brandPickerValue: this.data.form.brand ? [this.data.form.brand] : [],
      brandPickerVisible: true,
    })
  },
  onBrandConfirm(e) {
    const brand = e.detail.value[0]
    // 换品牌后清空已选等级（等级依赖品牌）
    this.setData({ 'form.brand': brand, 'form.tier': '', brandPickerVisible: false }, () => this._recheck())
  },

  // ── 等级 picker（依赖品牌联动）──
  openTierPicker() {
    const { curType, form } = this.data
    if (!form.brand) { wx.showToast({ title: '请先选品牌', icon: 'none' }); return }
    const tiers = TYPES[curType].brands[form.brand] || []
    if (form.brand === OTHER || tiers.length === 0) {
      // 「其他」品牌没有预置等级，走手填
      wx.showModal({
        title: '等级/卡种', editable: true, placeholderText: '手动输入',
        success: (r) => { if (r.confirm) this.setData({ 'form.tier': r.content || '' }, () => this._recheck()) },
      })
      return
    }
    this.setData({
      tierOptions: toOptions(tiers),
      tierPickerValue: form.tier ? [form.tier] : [],
      tierPickerVisible: true,
    })
  },
  onTierConfirm(e) {
    this.setData({ 'form.tier': e.detail.value[0], tierPickerVisible: false }, () => this._recheck())
  },

  // ── 积分体系 picker（仅信用卡）──
  openPointsPicker() {
    this.setData({
      pointsPickerValue: this.data.form.points ? [this.data.form.points] : [],
      pointsPickerVisible: true,
    })
  },
  onPointsConfirm(e) {
    this.setData({ 'form.points': e.detail.value[0], pointsPickerVisible: false })
  },

  onPickerCancel() {
    this.setData({ brandPickerVisible: false, tierPickerVisible: false, pointsPickerVisible: false })
  },

  // ── 表单输入 ──
  onIdInput(e) { this.setData({ 'form.idno': e.detail.value }) },
  onBrandOtherInput(e) { this.setData({ 'form.brandOther': e.detail.value }, () => this._recheck()) },

  // 校验：品牌 + 等级必填；「其他」品牌需填名称
  _recheck() {
    const f = this.data.form
    const brandOk = f.brand && (f.brand !== OTHER || f.brandOther.trim())
    this.setData({ canSave: !!(brandOk && f.tier) })
  },

  // ── 保存 ──
  onSave() {
    if (!this.data.canSave) return
    const { curType, form, editing } = this.data
    const brand = form.brand === OTHER ? form.brandOther.trim() : form.brand
    const entry = {
      id: form.id || ('e' + Date.now()),
      brand, tier: form.tier,
      idno: form.idno || '',
      points: curType === 'card' ? (form.points || '') : '',
    }
    const list = this._store[curType] || []
    const idx = list.findIndex((x) => x.id === entry.id)
    if (editing && idx >= 0) list[idx] = entry
    else list.push(entry)
    this._store[curType] = list
    wx.setStorageSync(STORE_KEY, this._store)
    this.setData({ formVisible: false })
    this.refresh()
  },

  onFormCancel() { this.setData({ formVisible: false }) },
  onFormClose(e) { this.setData({ formVisible: e.detail.visible }) },
})
