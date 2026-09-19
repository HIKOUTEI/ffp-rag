// 乘车记录录入。核心交互：输车次号 → 摊开全程停站 → 点上车站、点下车站 → 填日期存下。
//
// 三个「步骤」是同一页内的状态切换（step），不做多页跳转——用户点错了要能立刻退回去改。
//   search  搜车次
//   stops   展开停站表，点选区段
//   manual  手填兜底（搜不到车次时）
//
// ⚠️ 乘车日期不参与任何查询：数据源没有开行日历（见 spec「数据实测结论」），
//    每天的车次列表完全一样。所以这里**不做任何「这天这趟车开不开」的校验**，
//    补录 1990 年的行程也必须存得下。

const api = require('../../api')
const u = require('../../rail-util')

const SEARCH_DEBOUNCE = 300      // ms，边打字边搜，太快会把后端额度打光
const DATE_PICKER_START = '1950-01-01'  // TDesign 默认只让选近 10 年，补录历史会被挡住

// seq → '01' / '12' / '108'，两位以内补零，视觉上对齐
function padSeq(n) {
  return n < 10 ? '0' + n : '' + n
}

Page({
  data: {
    step: 'search',

    // ── 第 1 步：搜车次 ──
    keyword: '',
    searching: false,
    searched: false,        // 是否已经搜过一轮（用来区分「还没搜」与「搜了没结果」）
    results: [],

    // ── 第 2 步：停站表 ──
    loadingStops: false,
    train: null,            // {number, class, classTheme, origin, terminal, stop_count, totalKmText}
    stops: [],              // 见 _renderStops
    fromIdx: -1,            // 上车站在 stops 数组里的下标，-1 表示未选
    toIdx: -1,              // 下车站
    hintText: '',           // 提示条正文
    hasPick: false,         // 是否已选了上车站（决定「重选」可不可点）

    // ── 第 3 步：确认面板 ──
    confirmVisible: false,
    datePickerVisible: false,
    dateStart: DATE_PICKER_START,
    rideDate: '',
    note: '',
    saving: false,

    // ── 第 4 步：手填 ──
    manual: { trainNumber: '', rideDate: '', fromStation: '', toStation: '', note: '' },
    manualDatePickerVisible: false,
    canSaveManual: false,
  },

  onLoad() {
    this.setData({ rideDate: u.today(), 'manual.rideDate': u.today() })
  },

  onUnload() {
    if (this._timer) clearTimeout(this._timer)
  },

  // ==================== 第 1 步：搜车次 ====================

  // 防抖 300ms 后才发请求
  onKeywordChange(e) {
    const q = (e.detail.value || '').trim()
    this.setData({ keyword: e.detail.value || '' })
    if (this._timer) clearTimeout(this._timer)
    // 空输入直接清空，不发请求
    if (!q) {
      this._reqSeq = (this._reqSeq || 0) + 1
      this.setData({ results: [], searched: false, searching: false })
      return
    }
    this._timer = setTimeout(() => this._search(q), SEARCH_DEBOUNCE)
  },

  // 键盘「搜索」键：跳过防抖立刻搜
  onKeywordSubmit(e) {
    const q = (e.detail.value || '').trim()
    if (this._timer) clearTimeout(this._timer)
    if (q) this._search(q)
  },

  _search(q) {
    // 乱序返回保护：只认最后一次发出的请求
    const seq = (this._reqSeq = (this._reqSeq || 0) + 1)
    this.setData({ searching: true })
    api.rail.searchTrains(q).then((list) => {
      if (seq !== this._reqSeq) return
      // ⚠️ 29% 的车次号含 '/'（跨线换号，如 K551/K554），后端走别名表匹配，
      //    搜 K554 命中 K551/K554 是正常的。不过滤、不「纠正」，原样展示完整号。
      this.setData({
        searching: false,
        searched: true,
        results: list.map((t) => ({
          ...t,
          theme: u.classTheme(t.class),
          sub: t.origin + ' → ' + t.terminal + ' · ' + t.stop_count + ' 站 · 全程 ' + u.fmtKm(t.total_km),
        })),
      })
    }).catch((err) => {
      if (seq !== this._reqSeq) return
      this.setData({ searching: false })
      wx.showToast({ title: err.message, icon: 'none' })
    })
  },

  // ==================== 第 2 步：停站表 ====================

  onPickTrain(e) {
    const number = e.currentTarget.dataset.number
    this.setData({ loadingStops: true })
    api.rail.timetable(number).then((t) => {
      this.setData({
        loadingStops: false,
        step: 'stops',
        train: {
          // ⚠️ 入库要用后端返回的完整车次号，不是用户输入的那段别名
          number: t.number,
          class: t.class,
          theme: u.classTheme(t.class),
          origin: t.origin,
          terminal: t.terminal,
          stop_count: t.stop_count,
          totalKmText: u.fmtKm(t.total_km),
        },
        stops: this._renderStops(t.stops || []),
        fromIdx: -1,
        toIdx: -1,
      })
      this._syncHint()
      wx.pageScrollTo({ scrollTop: 0, duration: 0 })
    }).catch((err) => {
      this.setData({ loadingStops: false })
      wx.showToast({ title: err.message, icon: 'none' })
    })
  },

  // 停站 → 渲染结构。显示字段一次算好，点选时只改 mark，避免整表重排。
  _renderStops(raw) {
    const last = raw.length - 1
    return raw.map((s, i) => ({
      seq: s.seq,
      no: padSeq(s.seq),
      station: s.station,
      // ⚠️ 始发站没有到达时刻、终到站没有发车时刻，后端给的就是 null。
      //    显示破折号是正确的，不要回填成 00:00。
      arrival: u.fmtTime(s.arrival),
      departure: u.fmtTime(s.departure),
      // 跨日标注，实测最大 +3 天（有车次跑到 77:30:00）
      day: u.dayTag(s.day_offset),
      // 自始发站起的累计营业里程，与票面一致
      km: u.fmtKm(s.dist_km),
      _km: s.dist_km,
      edge: i === 0 ? 'origin' : (i === last ? 'terminal' : ''),
      first: i === 0,
      last: i === last,
      mark: '',
    }))
  },

  // 点一站：第一次点=上车站；再点更靠后的站=下车站；点到更靠前（或同一站）则重置为新的上车站。
  onTapStop(e) {
    const i = Number(e.currentTarget.dataset.i)
    const { fromIdx, toIdx } = this.data
    if (fromIdx < 0 || toIdx >= 0) {
      // 还没选 / 已经选完一段 → 开新一轮，这站当上车站
      this._select(i, -1)
    } else if (i <= fromIdx) {
      // 点回上车站或更靠前 → 重置为新的上车站，不报错
      this._select(i, -1)
    } else {
      this._select(fromIdx, i)
    }
  },

  onReset() {
    if (!this.data.hasPick) return
    this._select(-1, -1)
  },

  // 确认面板关掉后，点提示条能再叫回来——否则区段已选好却没有入口，只能重选一遍
  onHintTap() {
    const { fromIdx, toIdx } = this.data
    if (fromIdx >= 0 && toIdx >= 0) this.setData({ confirmVisible: true })
  },

  // 只把 mark 变了的那几行推给视图。上百站的车次（如 K 字头）整表 setData 会明显卡顿。
  _select(fromIdx, toIdx) {
    const stops = this.data.stops
    const patch = {}
    for (let i = 0; i < stops.length; i++) {
      let mark = ''
      if (fromIdx >= 0 && i === fromIdx) mark = 'from'
      else if (toIdx >= 0 && i === toIdx) mark = 'to'
      else if (fromIdx >= 0 && toIdx >= 0 && i > fromIdx && i < toIdx) mark = 'mid'
      if (stops[i].mark !== mark) {
        stops[i].mark = mark
        patch['stops[' + i + '].mark'] = mark
      }
    }
    patch.fromIdx = fromIdx
    patch.toIdx = toIdx
    this.setData(patch)
    this._syncHint()
  },

  // 提示条文案 + 区段选完自动滑出确认面板
  _syncHint() {
    const { stops, fromIdx, toIdx } = this.data
    if (fromIdx < 0) {
      this.setData({ hintText: '点一下上车站', hasPick: false })
      return
    }
    if (toIdx < 0) {
      this.setData({
        hintText: '已选上车站：' + stops[fromIdx].station + '，请选择下车站',
        hasPick: true,
      })
      return
    }
    const a = stops[fromIdx]
    const b = stops[toIdx]
    // 区段里程由前端即时算，只为反馈；入库后后端会重算一遍，以后端为准
    const km = (a._km === null || a._km === undefined || b._km === null || b._km === undefined)
      ? null : b._km - a._km
    this.setData({
      hintText: a.station + ' → ' + b.station + ' · ' + (toIdx - fromIdx + 1) + ' 站 · ' + u.fmtKm(km),
      hasPick: true,
      confirmVisible: true,
    })
  },

  // ==================== 第 3 步：日期与备注 ====================

  openDatePicker() { this.setData({ datePickerVisible: true }) },
  onDateConfirm(e) { this.setData({ rideDate: e.detail.value, datePickerVisible: false }) },
  onDateCancel() { this.setData({ datePickerVisible: false }) },

  onNoteChange(e) { this.setData({ note: e.detail.value || '' }) },

  onConfirmClose(e) { this.setData({ confirmVisible: e.detail.visible }) },
  onConfirmCancel() { this.setData({ confirmVisible: false }) },

  onSave() {
    const { train, stops, fromIdx, toIdx, rideDate, note, saving } = this.data
    if (saving || fromIdx < 0 || toIdx < 0) return
    this.setData({ saving: true })
    this._create({
      train_number: train.number,      // 完整车次号，不是用户输入的别名段
      ride_date: rideDate,
      from_seq: stops[fromIdx].seq,
      to_seq: stops[toIdx].seq,
      note: note || null,
      source: 'timetable',
    })
  },

  // ==================== 第 4 步：手填 ====================
  //
  // ⚠️ 手填记录不编造时刻、也不编造里程（spec 已定）。所以这张表单里
  //    既没有时刻输入框，也不许暗示「里程会自动算」——它不会。

  goManual() {
    // 把已输入的车次号带过去，省得重打
    const guess = (this.data.keyword || '').trim()
    this.setData({
      step: 'manual',
      'manual.trainNumber': this.data.manual.trainNumber || guess,
    }, () => this._recheckManual())
  },

  onManualInput(e) {
    const field = e.currentTarget.dataset.field
    this.setData({ ['manual.' + field]: e.detail.value || '' }, () => this._recheckManual())
  },

  openManualDatePicker() { this.setData({ manualDatePickerVisible: true }) },
  onManualDateConfirm(e) {
    this.setData({ 'manual.rideDate': e.detail.value, manualDatePickerVisible: false })
  },
  onManualDateCancel() { this.setData({ manualDatePickerVisible: false }) },

  // 后端要求手填记录起讫站名都非空，否则 422。这里先拦一道，省一次往返。
  _recheckManual() {
    const m = this.data.manual
    this.setData({
      canSaveManual: !!(m.trainNumber.trim() && m.rideDate && m.fromStation.trim() && m.toStation.trim()),
    })
  },

  onSaveManual() {
    const { manual: m, saving, canSaveManual } = this.data
    if (saving || !canSaveManual) return
    this.setData({ saving: true })
    this._create({
      train_number: m.trainNumber.trim(),
      ride_date: m.rideDate,
      from_station: m.fromStation.trim(),
      to_station: m.toStation.trim(),
      note: m.note || null,
      source: 'manual',
    })
  },

  // ==================== 公共 ====================

  // 后端 detail 已是现成中文用户文案（「没有找到车次 G999。」「铁路时刻表尚未同步，请稍后重试。」），
  // 由 api.js 透传成 Error.message，这里直接展示，不再包一层。
  _create(body) {
    api.rail.createJourney(body).then(() => {
      this.setData({ saving: false, confirmVisible: false })
      wx.showToast({ title: '已记录' })
      // 行程页 onShow 会自己刷新，不需要事件总线或全局变量
      setTimeout(() => wx.navigateBack(), 600)
    }).catch((err) => {
      this.setData({ saving: false })
      wx.showToast({ title: err.message, icon: 'none' })
    })
  },

  // 回到搜车次这一步。停站表留着不清，用户来回切不用重新加载。
  backToSearch() {
    this.setData({ step: 'search', confirmVisible: false })
  },
})
