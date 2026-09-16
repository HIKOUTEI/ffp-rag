// 微信登录 + token 管理。
// 首次/失效时 wx.login 拿 code → 后端 /auth/login 换 token → 存 Storage。
// 之后所有请求带 header: Authorization: Bearer <token>。
const { BASE_URL } = require('./config')

const TOKEN_KEY = 'ffp_token'

function getToken() {
  try { return wx.getStorageSync(TOKEN_KEY) || '' } catch (e) { return '' }
}

function setToken(t) {
  try { wx.setStorageSync(TOKEN_KEY, t || '') } catch (e) {}
}

// wx.login → code → 后端换 token。返回 Promise<token>。
function login() {
  return new Promise((resolve, reject) => {
    wx.login({
      success(res) {
        if (!res.code) { reject(new Error('wx.login 未返回 code')); return }
        wx.request({
          url: BASE_URL + '/auth/login',
          method: 'POST',
          header: { 'Content-Type': 'application/json' },
          data: { code: res.code },
          success(r) {
            const token = r.data && r.data.token
            if (r.statusCode === 200 && token) { setToken(token); resolve(token) }
            else reject(new Error((r.data && r.data.detail) || '登录失败'))
          },
          fail(err) { reject(new Error((err && err.errMsg) || '登录网络失败')) },
        })
      },
      fail(err) { reject(new Error((err && err.errMsg) || 'wx.login 失败')) },
    })
  })
}

// 确保有 token：有则直接用，无则登录换一个。
function ensureToken() {
  const t = getToken()
  if (t) return Promise.resolve(t)
  return login()
}

// 强制重新登录（token 失效 401 时用）。
function relogin() {
  setToken('')
  return login()
}

function authHeader() {
  const t = getToken()
  return t ? { Authorization: 'Bearer ' + t } : {}
}

module.exports = { getToken, ensureToken, login, relogin, authHeader }
