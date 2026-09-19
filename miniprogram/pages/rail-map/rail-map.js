// 打卡地图：把用户坐过的全部区段画成一张属于他自己的铁路版图。
//
// 三条硬约束，改动前先看：
// 1. 数据只来自 GET /rail/map 这一个请求。绝不要按车次逐个调 /rail/trains/{number}——
//    一个有 50 条记录的用户要发几十次请求，既慢又白耗 rail: 日额度。
// 2. 坐标后端已经转成 GCJ-02（backend/app/rail/geo.py），微信 <map> 用的就是 GCJ-02，
//    这里【不能再做任何坐标转换】，转了就整体偏 550 米。
// 3. 接口字段是 lat/lon，微信 polyline/marker 要的是 latitude/longitude，必须映射。
//
// 不做真实铁路线形：GTFS 没有 shapes.txt，只能车站点直连，画出来是折线不是铁轨走向。
// 这是 spec「明确不做」第一条，已知且接受。

const api = require('../../api')

// 车站多于这个数就只画到过 ≥2 次的站——几千个 marker 会把地图拖到卡顿
const MARKER_LIMIT = 200
// 没有 bounds（一条能画的记录都没有）时的兜底视野：中国全境
const FALLBACK_CENTER = { lat: 35.0, lon: 105.0 }
const FALLBACK_SCALE = 4
// 线路配色：品牌蓝 + cc 透明度（8 位 hex 是微信 polyline.color 的格式），
// 半透明让重叠的区段叠出层次，坐得多的线自然更深
const LINE_COLOR = '#0a84ffcc'

Page({
  data: {
    loading: true,
    error: '',
    isEmpty: false,
    // legs 为空但 stations 不为空（全是手填记录且站名都匹配上了）：
    // 地图上只有点没有线，得额外解释一句，否则用户以为是 bug
    lineless: false,
    // 车站过多，只画了到过 ≥2 次的站
    thinned: false,

    legCount: 0,
    stationCount: 0,

    center: FALLBACK_CENTER,
    scale: FALLBACK_SCALE,
    polyline: [],
    markers: [],
  },

  onLoad() {
    this.load()
  },

  load() {
    this.setData({ loading: true, error: '' })
    api.request('/rail/map')
      .then((res) => this._render(res || {}))
      .catch((e) => this.setData({ loading: false, error: (e && e.message) || '加载失败' }))
  },

  _render(res) {
    const legs = res.legs || []
    const stations = res.stations || []

    // 一条都没有 → 空状态，不渲染地图（空白地图比空状态更像故障）
    if (!legs.length && !stations.length) {
      this.setData({ loading: false, isEmpty: true })
      return
    }

    // 每条 leg 一段 polyline。points 已按 seq 升序，直接当点序列用。
    const polyline = legs
      .map((leg) => ({
        points: (leg.points || []).map((p) => ({ latitude: p.lat, longitude: p.lon })),
        color: LINE_COLOR,
        width: 4,
        arrowLine: false,
      }))
      // 只有 1 个点连不成线，微信会报错，直接丢掉
      .filter((line) => line.points.length >= 2)

    // 站太多就只留到过 ≥2 次的，并在右上角说明，免得用户以为丢数据
    const thinned = stations.length > MARKER_LIMIT
    const shown = thinned ? stations.filter((s) => (s.count || 0) >= 2) : stations
    const markers = shown.map((s, i) => ({
      // 微信建议 marker id 用 Number，更新 markers 时性能更好
      id: i,
      latitude: s.lat,
      longitude: s.lon,
      width: 16,
      height: 16,
      // 刻意不给 iconPath：本页不引入任何图片资源，用微信内置的默认针。
      // 标记点也做不了 cover-view——cover-view 不会跟着地图平移缩放。
      callout: {
        content: s.count > 1 ? s.name + ' · ' + s.count + ' 次' : s.name,
        display: 'BYCLICK',
        bgColor: '#ffffff',
        color: '#1c1c1e',
        fontSize: 12,
        padding: 8,
        borderRadius: 8,
      },
    }))

    this.setData({
      loading: false,
      isEmpty: false,
      lineless: polyline.length === 0,
      thinned,
      legCount: legs.length,
      stationCount: stations.length,
      center: this._centerOf(res.bounds),
      polyline,
      markers,
    }, () => this._fitView(res.bounds, legs, stations))
  },

  // bounds 的几何中心。只是 includePoints 生效前的一帧初值，别指望它精确。
  _centerOf(bounds) {
    if (!bounds) return FALLBACK_CENTER
    return {
      lat: (bounds.min_lat + bounds.max_lat) / 2,
      lon: (bounds.min_lon + bounds.max_lon) / 2,
    }
  },

  // 自动框住全部点。比自己按经纬度跨度反推 scale 靠谱，
  // 中老铁路那种跨境车次（万象、琅勃拉邦）也不会让视野崩掉。
  _fitView(bounds, legs, stations) {
    let points
    if (bounds) {
      // 有 bounds 就只喂两个对角点：框出来的矩形与喂全部点完全一致，
      // 但省掉上万个点的 setData 序列化开销
      points = [
        { latitude: bounds.min_lat, longitude: bounds.min_lon },
        { latitude: bounds.max_lat, longitude: bounds.max_lon },
      ]
    } else {
      points = []
      legs.forEach((leg) => (leg.points || []).forEach((p) => {
        points.push({ latitude: p.lat, longitude: p.lon })
      }))
      stations.forEach((s) => points.push({ latitude: s.lat, longitude: s.lon }))
    }
    if (!points.length) return

    const fit = () => {
      // padding 顺序是 [上, 右, 下, 左]。已知平台差异：
      // 安卓只认第一项（四边同值），开发者工具直接忽略 padding。真机再看留白。
      wx.createMapContext('railmap', this).includePoints({ points, padding: [60, 40, 60, 40] })
    }
    fit()
    // 真机上 map 偶尔还没布局完就收到 includePoints，补一次；同一组点，不会产生跳动
    setTimeout(fit, 300)
  },

  // 顶部信息条右侧的关闭按钮。正常都是从行程页 navigateTo 进来的，
  // 万一是从场景值/分享直接进来（无上一页），退化为回行程 tab。
  onClose() {
    wx.navigateBack({
      fail() { wx.switchTab({ url: '/pages/rail/rail' }) },
    })
  },

  // 空状态的「去记一趟车」。用 redirectTo 而不是 navigateTo：
  // 记完从录入页返回时不该又落回这张空地图。
  onGoEntry() {
    wx.redirectTo({ url: '/pages/rail-entry/rail-entry' })
  },
})
