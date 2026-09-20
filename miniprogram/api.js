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

// ---- 奖赏钱（RewardCash）----
// 后端接口见 backend/app/rewardcash/api.py，字段形状以 schemas.py + summary.py 为准。
//
// ⚠️ 全线「算不出来」一律是 **null，不是 0**（used / current / remaining / pct /
//    stock / projection 都可能整个为 null）。页面不得把 null 兜底成 0——
//    0 会被画成一条空进度条，等于告诉用户「还没开始用这个额度」。

// 规则集本地缓存的 Storage key。存 {version, ruleset}，与下发响应同形。
const RULESET_CACHE_KEY = 'rc_ruleset'

const reward = {
  // GET /rewardcash/rules  —— **不需登录**，规则是公开知识
  // → {version, ruleset: {
  //      categories: [{key, name, kind:'rate'|'flat'}],          ← 月结录入的输入框按这个顺序排
  //      rules: [{id, name, kind:'rate'|'flat', rate, flat_amount,
  //               recurrence:'recurring'|'one_off', reward_category|null,
  //               caps: [{kind:'spend'|'reward', amount, period}],
  //               threshold: {amount_hkd, period, scope:{region}} | null,
  //               requires_enrolment, conditions, period_start, period_end,
  //               status:'official'|'user_verified'|'unverified'|'unavailable',
  //               source:{url, clause, checked_at}, note}]}}
  //
  // 本地缓存 + ETag：请求带 If-None-Match: W/"rc-<version>"，后端命中回 304 空体，
  // 此时直接用缓存那份。规则一年改不了几次，每次冷启动全量拉是浪费。
  // 网络失败但本地有旧规则时**也返回旧的**：用去年的规则名渲染，好过整页打白。
  rules() {
    let cached = null
    try { cached = wx.getStorageSync(RULESET_CACHE_KEY) || null } catch (e) { cached = null }
    if (cached && !cached.ruleset) cached = null
    return new Promise((resolve, reject) => {
      const header = { 'Content-Type': 'application/json' }
      if (cached && cached.version) header['If-None-Match'] = 'W/"rc-' + cached.version + '"'
      wx.request({
        url: BASE_URL + '/rewardcash/rules',
        method: 'GET',
        header,
        success(res) {
          // 304 是命中缓存的正常路径，不是错误
          if (res.statusCode === 304) {
            if (cached) { resolve(cached); return }
            reject(new Error('规则缓存已失效，请重进本页'))
            return
          }
          if (res.statusCode >= 400) {
            if (cached) { resolve(cached); return }
            const detail = res.data && res.data.detail
            reject(new Error(typeof detail === 'string' && detail
              ? detail : '规则加载失败（' + res.statusCode + '）'))
            return
          }
          const data = res.data || {}
          if (!data.ruleset) {
            if (cached) { resolve(cached); return }
            reject(new Error('规则数据异常'))
            return
          }
          const fresh = { version: data.version, ruleset: data.ruleset }
          try { wx.setStorageSync(RULESET_CACHE_KEY, fresh) } catch (e) {}
          resolve(fresh)
        },
        fail(err) {
          if (cached) { resolve(cached); return }
          reject(new Error((err && err.errMsg) || '网络请求失败'))
        },
      })
    })
  },

  // GET /rewardcash/summary[?as_of=YYYY-MM-DD]（as_of 只为调试，线上不传）
  // → {as_of, ruleset_version,
  //    stock: {balance, expiring:{amount, date}, snapshot_at, from_month} | null,
  //        ↑ **一条月结都没有时整个是 null**；balance / expiring.amount / date /
  //          snapshot_at 各自也都可空。存量是快照，后端只取最新那月，不加总。
  //    flow: {range:{from, to, months},
  //           earned_by_category: [{key, name, kind, amount}],   ← 已按金额倒序
  //           total},
  //    caps: [{rule_id, rule_name, cap:{kind:'spend'|'reward', amount, period},
  //            window:{start, end} | null, used, remaining, pct,
  //            derivation, derivation_note}],
  //    thresholds: [{rule_id, rule_name, requirement, window, current, remaining,
  //                  met, derivation, derivation_note}],
  //    projection: {window_end, basis_months, recurring_per_month,
  //                 projected_additional, excluded_one_off, note} | null}
  //        ↑ **完整月不足 2 个时整个是 null**
  //
  // derivation 四取值，四种渲染，**不共用一套**（见 reward-util.capView）：
  //   rc_backsolve  由月结 RC ÷ 费率反推，used 有值
  //   spend_entries 由逐笔签账累计，current 有值
  //   not_enrolled  该规则要登记而用户未登记 → used/remaining/pct 全 null，签账一分不计
  //   unavailable   窗口或类别算不出来 → used/remaining/pct 全 null，看 derivation_note
  summary(asOf) {
    return request('/rewardcash/summary' + (asOf ? '?as_of=' + encodeURIComponent(asOf) : ''))
  },

  // PUT /rewardcash/months/{month}  幂等 upsert，重复提交安全（用户会反复回来改同一个月）
  // body: {flow: {earned: {'<category_key>': RC}},
  //        stock: {balance, expiring:{amount, date}, snapshot_at}}
  //   · earned 的 key 必须在规则集的 categories 白名单里，否则 422（不会静默收下）
  //   · stock 三个字段都可空，**空就传 null，不要传 0**
  //   · ⚠️ snapshot_at 只收 'YYYY-MM-DD'（后端 DATE_RE 是全匹配），
  //     带时分秒或时区的串会被 422 挡掉
  // → {month, flow:{earned}, stock:{balance, expiring:{amount,date}, snapshot_at},
  //    created_at, updated_at}
  putMonth(month, body) {
    return request('/rewardcash/months/' + encodeURIComponent(month), 'PUT', body)
  },

  // GET /rewardcash/months?limit=
  // → [{month, flow:{earned}, stock:{balance, expiring:{amount,date}, snapshot_at},
  //     created_at, updated_at}]，按月倒序
  listMonths(limit) {
    return request('/rewardcash/months?limit=' + (limit || 60))
      .then((r) => (r && r.months) || [])
  },

  deleteMonth(month) {
    return request('/rewardcash/months/' + encodeURIComponent(month), 'DELETE')
  },

  // POST /rewardcash/spends
  // body: {spend_date:'YYYY-MM-DD', amount, currency, amount_hkd,
  //        region:'mainland'|'macau'|'hongkong'|'overseas',
  //        merchant_category:'dining'|'other',
  //        channel:'rewardplus_qr'|'unionpay_qr'|'mobile_pay'|'physical_card'
  //                |'alipayhk'|'wechat'|'online'|'other',
  //        settled_hkd:bool, card, note}
  //   amount_hkd 必填：后端不接汇率服务，人民币／澳门币前端按 1:1 预填
  // → {id}
  createSpend(body) { return request('/rewardcash/spends', 'POST', body) },

  // GET /rewardcash/spends?date_from=&date_to=&limit=
  //   ⚠️ query 参数叫 date_from / date_to（不是 from / to）
  // → [{id, spend_date, amount, currency, amount_hkd, region, merchant_category,
  //     channel, settled_hkd(bool), card, note}]，按日期倒序
  listSpends(opts) {
    const o = opts || {}
    let q = '?limit=' + (o.limit || 200)
    if (o.dateFrom) q += '&date_from=' + encodeURIComponent(o.dateFrom)
    if (o.dateTo) q += '&date_to=' + encodeURIComponent(o.dateTo)
    return request('/rewardcash/spends' + q).then((r) => (r && r.spends) || [])
  },

  // PATCH /rewardcash/spends/{id}，只传要改的字段 → {ok:true}
  updateSpend(id, fields) { return request('/rewardcash/spends/' + id, 'PATCH', fields) },

  deleteSpend(id) { return request('/rewardcash/spends/' + id, 'DELETE') },

  // GET /rewardcash/settings
  // → {enrolled: {'<rule_id>': 'YYYY-MM-DD' | null}, membership_year_start, travel_guru_tier}
  //   enrolled 是**三态**：key 不存在 = 没问过；null = 确认未登记；日期 = 已登记。
  //   别在页面里压成开关的两态——登记日决定从哪天起计。
  settings() { return request('/rewardcash/settings') },

  // PUT /rewardcash/settings 整份覆盖，**客户端必须回传完整的 enrolled**
  // body: {enrolled, membership_year_start, travel_guru_tier:'go'|'ging'|'guru'|null}
  // → 与 GET 同形
  putSettings(body) { return request('/rewardcash/settings', 'PUT', body) },

  // DELETE /rewardcash/data 清空本人的月结／逐笔／设置，但**保留账号**
  // → {months, spends, settings}（各删了几行）
  clearData() { return request('/rewardcash/data', 'DELETE') },
}

module.exports = { conversationStream, popularQuestions, reportCorrection, request, rail, reward }
