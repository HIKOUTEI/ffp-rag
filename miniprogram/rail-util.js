// 「行程」三个页面共用的纯函数。放这里是为了三处显示口径一致：
// 同一个 day_offset、同一段里程，在列表、录入页、地图页必须长得一样。

// 今天，'YYYY-MM-DD'。乘车日期只是记录元数据，不参与查询（GTFS 无开行日历）。
function today() {
  const d = new Date()
  const p = (n) => (n < 10 ? '0' + n : '' + n)
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate())
}

// '2026-09-17' → '9月17日'；非今年则带年份 '2024年9月17日'
function fmtDate(s) {
  if (!s) return ''
  const parts = s.split('-')
  if (parts.length !== 3) return s
  const y = +parts[0]
  const md = +parts[1] + '月' + +parts[2] + '日'
  return y === new Date().getFullYear() ? md : y + '年' + md
}

// 跨日标注。实测最大 +3 天（77:30:00）。0 返回空串，别显示「+0天」。
function dayTag(offset) {
  return offset > 0 ? '+' + offset + '天' : ''
}

// 里程。null（手填记录 / 数据缺失）显示破折号，不显示 0。
function fmtKm(v) {
  if (v === null || v === undefined) return '—'
  return (Math.round(v * 10) / 10) + ' km'
}

// 'HH:MM' 或 null（始发站无到达、终到站无发车）
function fmtTime(t) {
  return t || '—'
}

// 车次种别 → t-tag theme。实测共 13 类，未列出的走 default。
// 只分「高铁动车系 / 普速系 / 市域市郊」三档，不给 13 个颜色——那是噪音。
const CLASS_THEME = {
  高速动车: 'primary', 动车组: 'primary', 城际高速: 'primary',
  市域: 'success', 市郊: 'success',
  新空调快速: 'warning', 新空调特快: 'warning', 新空调直特: 'warning',
  新空调普快: 'warning', 新空调普客: 'warning', 普快: 'warning', 普客: 'warning',
  旅游: 'default',
}
function classTheme(cls) {
  return CLASS_THEME[cls] || 'default'
}

module.exports = { today, fmtDate, dayTag, fmtKm, fmtTime, classTheme }
