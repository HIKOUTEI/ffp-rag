const { conversationStream, popularQuestions, reportCorrection } = require('../../api')

const STORE_KEY = 'ffp_current_conversation'
// AI 头像用 base64 的小飞机 emoji 不便，用一张远程/本地图；这里用 data URI 占位
const AI_AVATAR = 'https://tdesign.gtimg.com/site/chat-avatar.png'

Page({
  data: {
    // [{role, content:[{type:'markdown',data}], status, question?, rewritten?, sources?, reported?}]
    // question/rewritten/sources 只挂在 AI 消息上，供报错时上传快照（ADR-0005）
    messages: [],
    input: '',
    sending: false,
    popular: [],
    scrollTop: 0,
    aiAvatar: AI_AVATAR,
    disclaimer: '答案由 AI 基于收录资料生成，可能过时或有误，请以官方渠道为准。',
  },

  onLoad() {
    const saved = wx.getStorageSync(STORE_KEY)
    if (saved && saved.length) {
      this.setData({ messages: saved })
      this.scrollToBottom()
    } else {
      this.loadPopular()
    }
  },

  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setActive('pages/chat/chat')
    }
  },

  loadPopular() {
    popularQuestions(4).then((qs) => this.setData({ popular: qs }))
  },

  // chat-sender 的 change 事件：{ value }
  onInput(e) { this.setData({ input: e.detail.value }) },

  onTapPopular(e) {
    this.send(e.currentTarget.dataset.text)
  },

  // chat-sender 的 send 事件：{ value }
  onSend(e) {
    const text = ((e && e.detail && e.detail.value) || this.data.input || '').trim()
    if (text) this.send(text)
  },

  // chat-sender loading 态点击停止
  onStop() {
    if (this.task) { try { this.task.abort() } catch (err) {} }
    this.finish()
  },

  onNewChat() {
    if (this.task) { try { this.task.abort() } catch (e) {} }
    wx.removeStorageSync(STORE_KEY)
    this.setData({ messages: [], input: '', sending: false, popular: [] })
    this.loadPopular()
  },

  send(text) {
    if (this.data.sending) return
    const userMsg = { role: 'user', content: [{ type: 'text', data: text }] }
    // AI 占位：status=pending 时组件自动显示加载动画
    // question/sources 随流式事件回填，供之后报错时上传
    const aiMsg = {
      role: 'assistant', content: [{ type: 'markdown', data: '' }], status: 'pending',
      question: text, rewritten: '', sources: [], reported: false,
    }
    const messages = this.data.messages.concat([userMsg, aiMsg])
    const aiIndex = messages.length - 1

    this.setData({ messages, input: '', sending: true, popular: [] })
    this.scrollToBottom()

    // 传后端历史：从 content 数组还原为 {role, content}；
    // 过滤掉正在生成的 AI 占位（pending），此时列表已含当前用户问题
    const wire = messages
      .filter((m) => !(m.role === 'assistant' && m.status === 'pending'))
      .map((m) => ({ role: m.role, content: m.content.map((c) => c.data).join('') }))

    let acc = ''
    this.task = conversationStream(wire, {
      onRewritten: (t) => {
        this.patchAi(aiIndex, { rewritten: t })
      },
      onSources: (list) => {
        this.patchAi(aiIndex, { sources: list || [] })
      },
      onDelta: (delta) => {
        acc += delta
        this.patchAi(aiIndex, { 'content[0].data': acc, status: 'complete' })
        this.scrollToBottom()
      },
      onDone: () => {
        this.patchAi(aiIndex, { status: 'complete' })
        this.finish()
      },
      onError: (err) => {
        const msg = '⚠️ ' + (err.message || '出错了，请重试')
        this.patchAi(aiIndex, { 'content[0].data': msg, status: 'error' })
        this.finish()
      },
    })
  },

  // 点「👎 报错」：收一句选填说明，连同问答快照上报（ADR-0005）。
  // 说明不强制——摩擦越低上报量越大，空白条目由管理员自行判断。
  onReport(e) {
    const i = e.currentTarget.dataset.index
    const msg = this.data.messages[i]
    if (!msg || msg.reported) return

    wx.showModal({
      title: '哪里不对？',
      editable: true,
      placeholderText: '选填，写一句能帮我们更快修正',
      confirmText: '提交',
      success: (res) => {
        if (!res.confirm) return
        const sources = msg.sources || []
        reportCorrection({
          question: msg.question || '',
          rewritten: msg.rewritten || '',
          answer: msg.content.map((c) => c.data).join(''),
          doc_ids: sources.map((s) => s.doc_id).filter((id) => !!id),
          sources,
          note: (res.content || '').trim(),
        }).then(() => {
          // messages 本就会写进 Storage，标记随之持久化
          this.patchAi(i, { reported: true })
          wx.setStorageSync(STORE_KEY, this.data.messages)
          wx.showToast({ title: '已收到，感谢反馈', icon: 'none' })
        }).catch((err) => {
          wx.showToast({ title: err.message || '提交失败', icon: 'none' })
        })
      },
    })
  },

  // 直接按 setData 路径更新，避免整列表重渲染
  patchAi(i, patch) {
    const prefix = 'messages[' + i + '].'
    const obj = {}
    Object.keys(patch).forEach((k) => { obj[prefix + k] = patch[k] })
    this.setData(obj)
  },

  finish() {
    this.setData({ sending: false })
    this.task = null
    wx.setStorageSync(STORE_KEY, this.data.messages)
  },

  scrollToBottom() {
    this.setData({ scrollTop: 1e8 })
  },
})
