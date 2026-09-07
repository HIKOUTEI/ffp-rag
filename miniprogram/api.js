// 极简 SSE over wx.request(enableChunked) 客户端。
// 微信 onChunkReceived 给的是 ArrayBuffer，需自行拼接 UTF-8 并按 \n\n 切帧。
// 注意：enableChunked 的流式效果只能在【真机】验证，开发者工具支持有限。

const { BASE_URL } = require('./config')

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
    header: { 'Content-Type': 'application/json' },
    data: { messages },
    enableChunked: true,
    responseType: 'arraybuffer',
    success(res) {
      // enableChunked 下 body 走 onChunkReceived，这里只用 statusCode 判非流式错误（如 500/4xx）
      if (res && res.statusCode >= 400) {
        httpFailed = true
        fail('服务出错（' + res.statusCode + '），请稍后重试')
      }
    },
    fail(err) {
      fail((err && err.errMsg) || '网络请求失败')
    },
    complete() {
      // 正常流应以 done 事件收尾；若连接结束仍未收到 done，且非已知错误，则提示中断
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

  // 包一层 abort：主动取消（如「新对话」）不应触发 complete 里的「连接已中断」误报
  const rawAbort = task.abort && task.abort.bind(task)
  if (rawAbort) {
    task.abort = function () { done = true; rawAbort() }
  }

  return task
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

module.exports = { conversationStream, popularQuestions }
