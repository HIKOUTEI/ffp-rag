// 极简 SSE over wx.request(enableChunked) 客户端。
// 微信 onChunkReceived 给的是 ArrayBuffer，需自行拼接 UTF-8 并按 \n\n 切帧。
// 注意：enableChunked 的流式效果只能在【真机】验证，开发者工具支持有限。

const { BASE_URL } = require('./config')
const auth = require('./auth')

// 把 ArrayBuffer 解成 UTF-8 字符串（TextDecoder 在小程序基础库 2.x 可用）
function decodeUTF8(buf) {
  if (typeof TextDecoder !== 'undefined') {
    return new TextDecoder('utf-8').decode(new Uint8Array(buf))
  }
  // 兜底：逐字节（仅 ASCII 安全，正常不会走到）
  const bytes = new Uint8Array(buf)
  let s = ''
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i])
  return decodeURIComponent(escape(s))
}

// 解析一个 SSE 帧文本 → { event, data }
function parseFrame(frame) {
  let event = 'message'
  const dataLines = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  return { event, data: dataLines.join('\n') }
}

/**
 * 发起多轮流式对话。
 * @param {Array} messages [{role, content}]
 * @param {object} handlers { onRewritten, onSources, onDelta, onDone, onError }
 * @returns requestTask（可 .abort()）
 */
function conversationStream(messages, handlers) {
  const h = handlers || {}
  // 包装 task：token 是异步拿的，先返回一个占位可 abort 对象，拿到 token 后再挂真实请求。
  const wrapper = { _real: null, _aborted: false, abort() { this._aborted = true; if (this._real && this._real.abort) this._real.abort() } }

  function start(token, isRetry) {
    let buffer = ''
    let done = false
    let httpFailed = false

    function fail(msg) {
      if (done) return
      done = true
      if (h.onError) h.onError(new Error(msg))
    }

    const task = wx.request({
      url: BASE_URL + '/chat/conversation/stream',
      method: 'POST',
      header: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
      data: { messages },
      enableChunked: true,
      responseType: 'arraybuffer',
      success(res) {
        // 401：token 失效，自动重登并重试一次
        if (res && res.statusCode === 401 && !isRetry && !wrapper._aborted) {
          done = true
          auth.relogin().then((t) => start(t, true)).catch(() => fail('登录失效，请重试'))
          return
        }
        if (res && res.statusCode >= 400) {
          httpFailed = true
          const msg = res.statusCode === 429 ? '今日提问次数已达上限，请明天再来'
            : '服务出错（' + res.statusCode + '），请稍后重试'
          fail(msg)
        }
      },
      fail(err) {
        fail((err && err.errMsg) || '网络请求失败')
      },
      complete() {
        if (!done && !httpFailed) fail('连接已中断，请重试')
      },
    })

    task.onChunkReceived((res) => {
      if (done) return
      buffer += decodeUTF8(res.data)
      let idx
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        if (!frame.trim()) continue
        const { event, data } = parseFrame(frame)
        let payload = {}
        try { payload = data ? JSON.parse(data) : {} } catch (e) { payload = {} }
        if (event === 'rewritten' && h.onRewritten) h.onRewritten(payload.text || '')
        else if (event === 'sources' && h.onSources) h.onSources(payload || [])
        else if (event === 'delta' && h.onDelta) h.onDelta(payload.text || '')
        else if (event === 'done') { done = true; if (h.onDone) h.onDone() }
      }
    })

    const rawAbort = task.abort && task.abort.bind(task)
    if (rawAbort) {
      task.abort = function () { done = true; rawAbort() }
    }
    wrapper._real = task
    if (wrapper._aborted) task.abort()
  }

  // 先确保有 token，再发起流式请求
  auth.ensureToken()
    .then((t) => { if (!wrapper._aborted) start(t, false) })
    .catch(() => { if (h.onError) h.onError(new Error('登录失败，请重试')) })

  return wrapper
}

// 拉取热门问题（首屏空状态用）
function popularQuestions(n) {
  return new Promise((resolve) => {
    wx.request({
      url: BASE_URL + '/popular-questions?n=' + (n || 4),
      method: 'GET',
      success(res) {
        const qs = (res.data && res.data.questions) || []
        resolve(qs)
      },
      fail() { resolve([]) },
    })
  })
}

// 上报一条纠错记录（用户点「👎 报错」）。
// 快照由前端上传（见 ADR-0005）；401 时自动重登重试一次。
// 返回 Promise，reject 的 Error.message 可直接展示给用户。
function reportCorrection(payload) {
  return new Promise((resolve, reject) => {
    function post(token, isRetry) {
      wx.request({
        url: BASE_URL + '/feedback/correction',
        method: 'POST',
        header: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
        data: payload,
        success(res) {
          if (res.statusCode === 401 && !isRetry) {
            auth.relogin().then((t) => post(t, true)).catch(() => reject(new Error('登录失效，请重试')))
            return
          }
          if (res.statusCode === 429) { reject(new Error('今日反馈次数已达上限')); return }
          if (res.statusCode >= 400) { reject(new Error('提交失败（' + res.statusCode + '）')); return }
          resolve()
        },
        fail(err) { reject(new Error((err && err.errMsg) || '网络请求失败')) },
      })
    }
    auth.ensureToken().then((t) => post(t, false)).catch(() => reject(new Error('登录失败，请重试')))
  })
}

// ---- 通用带鉴权请求 ----
// 沿用 reportCorrection 的约定：401 自动重登并重试一次，reject 出来的 Error.message
// 可直接 wx.showToast 给用户看。后端 HTTPException 的 detail 本身就是中文用户文案
// （如「没有找到车次 G999。」「下车站必须在上车站之后。」），故原样透传。
function request(path, method, data) {
  return new Promise((resolve, reject) => {
    function send(token, isRetry) {
      wx.request({
        url: BASE_URL + path,
        method: method || 'GET',
        header: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
        data: data,
        success(res) {
          if (res.statusCode === 401 && !isRetry) {
            auth.relogin().then((t) => send(t, true)).catch(() => reject(new Error('登录失效，请重试')))
            return
          }
          if (res.statusCode < 400) { resolve(res.data); return }
          const detail = res.data && res.data.detail
          if (typeof detail === 'string' && detail) { reject(new Error(detail)); return }
          reject(new Error(res.statusCode === 429 ? '今日查询次数已达上限，请明天再来'
            : '请求失败（' + res.statusCode + '）'))
        },
        fail(err) { reject(new Error((err && err.errMsg) || '网络请求失败')) },
      })
    }
    auth.ensureToken().then((t) => send(t, false)).catch(() => reject(new Error('登录失败，请重试')))
  })
}

// ---- 铁路乘车记录 ----
// 后端接口见 backend/app/rail/api.py。注意车次号 29% 含 '/'（K551/K554），
// 放进 path 前必须 encodeURIComponent。
const rail = {
  // → [{number, class, origin, terminal, stop_count, total_km}]，最多 20 条
  searchTrains(q) {
    if (!q) return Promise.resolve([])
    return request('/rail/trains?q=' + encodeURIComponent(q)).then((r) => (r && r.trains) || [])
  },

  // → {number, class, origin, terminal, stop_count, total_km, gtfs_version,
  //    stops: [{seq, station, arrival, departure, day_offset, dist_km, lat, lon}]}
  // 时刻为 'HH:MM' 或 null（始发站无到达、终到站无发车）；坐标已是 GCJ-02，可直接喂 <map>。
  timetable(number) {
    return request('/rail/trains/' + encodeURIComponent(number))
  },

  // body: {train_number, ride_date:'YYYY-MM-DD', from_seq, to_seq, note, source:'timetable'}
  //   或 {train_number, ride_date, from_station, to_station, note, source:'manual'}
  // → {id}
  createJourney(body) { return request('/rail/journeys', 'POST', body) },

  // → [{id, train_number, ride_date, from_station, to_station, from_seq, to_seq,
  //     note, departure, arrival, day_offset, distance_km, stale, source, ...}]
  // 按乘车日期倒序。stale=true 表示车次已不在当前运行图里，时刻/里程为 null。
  listJourneys(limit, offset) {
    const q = '?limit=' + (limit || 50) + '&offset=' + (offset || 0)
    return request('/rail/journeys' + q).then((r) => (r && r.journeys) || [])
  },

  // 只能改 ride_date / note
  updateJourney(id, fields) { return request('/rail/journeys/' + id, 'PATCH', fields) },

  deleteJourney(id) { return request('/rail/journeys/' + id, 'DELETE') },

  // 清空全部 → {deleted: n}
  clearJourneys() { return request('/rail/journeys', 'DELETE') },

  // → {journey_count, total_km, station_count, city_count, province_count,
  //    class_counts:{种别:次数}, first_ride, latest_ride}
  stats() { return request('/rail/stats') },
}

module.exports = { conversationStream, popularQuestions, reportCorrection, request, rail }
