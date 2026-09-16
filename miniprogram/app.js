const auth = require('./auth')

App({
  globalData: {},
  onLaunch() {
    // 启动即静默登录（wx.login 不弹窗），换取 token 供问答接口使用。
    auth.ensureToken().catch(() => {
      // 登录失败不阻塞启动；发消息时会再尝试并提示。
    })
  },
})
