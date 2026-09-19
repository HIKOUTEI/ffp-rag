// 「行程」tab 首屏：统计卡片 → 乘车记录列表 → 数据与隐私。
//
// 渲染口径全部走 rail-util，**不在 wxml 里做格式化**——同一个 day_offset / 里程
// 在列表、录入页、地图页必须长得一样，所以在 JS 里预先算好视图模型再 setData。
const api = require('../../api')
const u = require('../../rail-util')

// 一页 50 条。记录量级本来就小，不做无限滚动，满页才给「加载更多」。
const PAGE_SIZE = 50
// 车次种别标签最多展示 4 种，超出直接截断（不做「更多」入口）
const CLASS_TAG_MAX = 4
// 注销账号的二次确认口令：必须一字不差地手打
const LOGOUT_WORD = '注销'

Page({
  data: {
    loading: true,          // 首次加载中（避免空状态一闪而过）
    loadingMore: false,

    // ── 统计 ──
    stats: null,            // 后端原样返回，journey_count === 0 时整卡不渲染
    totalKm: '0',           // 主数字，单位「km」在 wxml 里用小字另排
    classTags: [],          // [{text:'高速动车 ×30', theme}]

    // ── 列表 ──
    journeys: [],           // 视图模型，见 _toView
    hasMore: false,

    // ── 编辑面板（只能改乘车日期与备注）──
    editVisible: false,
    editId: '',
    editTitle: '',          // 面板副标题：车次 · 起讫站
    editDate: '',           // 'YYYY-MM-DD'
    editDateText: '',       // 给 t-cell 显示的中文日期
    editNote: '',
    datePickerVisible: false,

    // ── 注销账号第二道确认 ──
    logoutVisible: false,
    logoutInput: '',
  },

  onShow() {
    // 自定义 tabBar 必须在每个 tab 页 onShow 里高亮自己，否则切回来是灰的
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setActive('pages/rail/rail')
    }
    // 从录入页 navigateBack 回来也会走这里，列表自动刷新，不需要额外回调机制
    this.refresh()
  },

  // ── 数据加载 ──

  // 统计与首页列表一起拉。任一失败都提示，但不互相阻塞渲染。
  refresh() {
    api.rail.stats()
      .then((s) => this._applyStats(s))
      .catch((err) => this._toast(err))

    api.rail.listJourneys(PAGE_SIZE, 0)
      .then((list) => {
        this.setData({
          loading: false,
          journeys: list.map(this._toView),
          hasMore: list.length >= PAGE_SIZE,
        })
      })
      .catch((err) => {
        this.setData({ loading: false })
        this._toast(err)
      })
  },

  onLoadMore() {
    if (this.data.loadingMore) return
    this.setData({ loadingMore: true })
    api.rail.listJourneys(PAGE_SIZE, this.data.journeys.length)
      .then((list) => {
        this.setData({
          loadingMore: false,
          journeys: this.data.journeys.concat(list.map(this._toView)),
          hasMore: list.length >= PAGE_SIZE,
        })
      })
      .catch((err) => {
        this.setData({ loadingMore: false })
        this._toast(err)
      })
  },

  _applyStats(s) {
    // 主数字与列表里的里程共用 fmtKm 的舍入口径，只是把单位摘出来单独排版，
    // 免得 " km" 混进 48rpx 的大号数字里。
    const totalKm = u.fmtKm(s.total_km).replace(' km', '')
    // class_counts 后端已按次数倒序，JSON 解析保留键序，直接截前 4 种
    const classTags = Object.keys(s.class_counts || {})
      .slice(0, CLASS_TAG_MAX)
      .map((name) => ({ text: name + ' ×' + s.class_counts[name], theme: u.classTheme(name) }))
    this.setData({ stats: s, totalKm, classTags })
  },

  // 一条乘车记录 → 视图模型。
  // stale（车次停运/改点）与 manual（手填）两种情况下 departure/arrival/distance_km
  // 都是 null，fmtTime/fmtKm 显示破折号，这是正确表现，不要补零。
  _toView(j) {
    return {
      id: j.id,
      trainNumber: j.train_number,
      rideDate: j.ride_date,
      dateText: u.fmtDate(j.ride_date),
      fromStation: j.from_station,
      toStation: j.to_station,
      depText: u.fmtTime(j.departure),
      arrText: u.fmtTime(j.arrival),
      dayTag: u.dayTag(j.day_offset),   // 0 / null 都返回空串，不渲染那个角标
      kmText: u.fmtKm(j.distance_km),
      note: j.note || '',
      stale: j.stale === true,
      manual: j.source === 'manual',
    }
  },

  _find(id) {
    return this.data.journeys.find((x) => x.id === id)
  },

  // api.js 的 reject 消息本身就是中文用户文案，原样展示
  _toast(err) {
    wx.showToast({ title: (err && err.message) || '操作失败', icon: 'none' })
  },

  // ── 跳转 ──

  onOpenMap() {
    wx.navigateTo({ url: '/pages/rail-map/rail-map' })
  },

  onAdd() {
    wx.navigateTo({ url: '/pages/rail-entry/rail-entry' })
  },

  // ── 删除单条 ──

  onDelete(e) {
    const id = e.currentTarget.dataset.id
    const item = this._find(id)
    if (!item) return
    wx.showModal({
      title: '删除这条记录？',
      content: item.trainNumber + ' · ' + item.dateText,
      confirmColor: '#ff3b30',
      success: (r) => {
        if (!r.confirm) return
        api.rail.deleteJourney(id)
          .then(() => {
            wx.showToast({ title: '已删除', icon: 'none' })
            this.refresh()
          })
          .catch((err) => this._toast(err))
      },
    })
  },

  // ── 编辑（只认乘车日期与备注，改车次/站点请删了重录）──

  onEdit(e) {
    const item = this._find(e.currentTarget.dataset.id)
    if (!item) return
    this.setData({
      editVisible: true,
      editId: item.id,
      editTitle: item.trainNumber + ' · ' + item.fromStation + ' → ' + item.toStation,
      editDate: item.rideDate,
      editDateText: item.dateText,
      editNote: item.note,
    })
  },

  onEditClose(e) { this.setData({ editVisible: e.detail.visible }) },
  onEditCancel() { this.setData({ editVisible: false }) },
  onNoteInput(e) { this.setData({ editNote: e.detail.value }) },

  openDatePicker() { this.setData({ datePickerVisible: true }) },
  onDateCancel() { this.setData({ datePickerVisible: false }) },
  onDateConfirm(e) {
    const date = e.detail.value   // format 已指定为 YYYY-MM-DD
    this.setData({ datePickerVisible: false, editDate: date, editDateText: u.fmtDate(date) })
  },

  onEditSave() {
    const { editId, editDate, editNote } = this.data
    api.rail.updateJourney(editId, { ride_date: editDate, note: editNote })
      .then(() => {
        this.setData({ editVisible: false })
        wx.showToast({ title: '已保存', icon: 'none' })
        this.refresh()
      })
      .catch((err) => this._toast(err))
  },

  // ── 数据与隐私（个保法要求，见 spec「上线前必办」）──

  // 导出：后端返回完整 JSON → 写进本地文件 → 转发给微信好友/文件传输助手
  onExport() {
    wx.showLoading({ title: '正在导出', mask: true })
    api.request('/rail/export')
      .then((data) => {
        wx.hideLoading()
        const fs = wx.getFileSystemManager()
        const path = `${wx.env.USER_DATA_PATH}/ffp-rail-export.json`
        fs.writeFile({
          filePath: path,
          data: JSON.stringify(data, null, 2),
          encoding: 'utf8',
          // 用户在转发面板点取消也会走 fail，所以这里静默，不弹错误提示
          success: () => wx.shareFileMessage({ filePath: path, fileName: '我的乘车记录.json', fail: () => {} }),
          fail: () => wx.showToast({ title: '写入文件失败', icon: 'none' }),
        })
      })
      .catch((err) => {
        wx.hideLoading()
        this._toast(err)
      })
  },

  onClear() {
    wx.showModal({
      title: '清空全部记录？',
      content: '你的全部乘车记录将被删除，不可恢复。',
      confirmColor: '#ff3b30',
      success: (r) => {
        if (!r.confirm) return
        api.rail.clearJourneys()
          .then((res) => {
            wx.showToast({ title: '已清空 ' + ((res && res.deleted) || 0) + ' 条', icon: 'none' })
            this.refresh()
          })
          .catch((err) => this._toast(err))
      },
    })
  },

  // 注销账号：两道确认。第一道说明后果，第二道要求手打「注销」二字。
  onDeleteAccount() {
    wx.showModal({
      title: '注销账号',
      content: '将永久删除你的全部乘车记录，不可恢复。',
      confirmText: '继续',
      confirmColor: '#ff3b30',
      success: (r) => {
        if (!r.confirm) return
        this.setData({ logoutVisible: true, logoutInput: '' })
      },
    })
  },

  onLogoutInput(e) { this.setData({ logoutInput: e.detail.value }) },
  onLogoutCancel() { this.setData({ logoutVisible: false }) },

  onLogoutConfirm() {
    // 口令不对就停在对话框里，不关闭——用户还能接着改
    if (this.data.logoutInput.trim() !== LOGOUT_WORD) {
      wx.showToast({ title: '请输入「' + LOGOUT_WORD + '」二字', icon: 'none' })
      return
    }
    this.setData({ logoutVisible: false })
    wx.showLoading({ title: '正在注销', mask: true })
    api.request('/rail/account', 'DELETE')
      .then(() => {
        wx.hideLoading()
        // 清掉本机登录态与档案；下次 wx.login 会拿到全新的 user_id，从零开始
        wx.clearStorageSync()
        wx.reLaunch({ url: '/pages/chat/chat' })
      })
      .catch((err) => {
        wx.hideLoading()
        this._toast(err)
      })
  },
})
