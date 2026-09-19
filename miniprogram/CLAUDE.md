# miniprogram —— 微信小程序端

原生小程序（无框架、CommonJS `require`），UI 组件用 TDesign。

## 模块职责

```
config.js     BASE_URL + 领域中文标签。本地联调改 BASE_URL，别在别处硬编码地址
auth.js       wx.login → /auth/login 换 token → Storage。token key: ffp_token
api.js        所有后端调用的唯一出口
catalog.js    领域/分类常量
rail-util.js  乘车记录的纯函数工具
styles/       跨页共用样式，页面在 wxss 顶部 @import
```

## 硬性约定

**任何网络请求都走 `api.js`，页面里不要直接 `wx.request`。** `api.js` 的通用
`request(path, method, data)` 已经封好三件事：

1. `auth.ensureToken()` 自动登录
2. 401 自动 `relogin()` 并**重试一次**
3. 后端 `HTTPException.detail` 原样 reject 出来 —— 所以 `catch` 里的
   `err.message` 可以直接 `wx.showToast`，不要再包一层自己的文案

新增后端接口时，在 `api.js` 里加方法并**在方法上方用注释写清返回结构**（照
`rail` 那几个方法的写法）。这些注释是小程序侧唯一的契约文档，没有类型系统兜底。

## 页面约定

每个页面四件套 `.js/.json/.wxml/.wxss`，新增页面必须同时：

- 在 `app.json` 的 `pages` 数组注册
- 如果进 tabBar，还要改 `app.json` 的 `tabBar.list` **和** `custom-tab-bar/`
  （`"custom": true`，tabBar 是自定义组件，不是原生的）
- 组件在 `app.json` 的 `usingComponents` 全局注册，页面 `.json` 里一般不用再写

样式沿用 `app.wxss` 的设计系统变量（`--brand` / `--surface` / `--radius-lg` /
`--shadow-soft`），**不要另立一套颜色和圆角**。行程三页共用 `styles/rail.wxss`。

单位用 `rpx`；底部留白记得 `env(safe-area-inset-bottom)`。

## 两个坑

**车次号 29% 含 `/`（如 `K551/K554`）。** 放进 URL path 前必须
`encodeURIComponent`，否则路由直接错配。

**SSE 只能在真机验证。** `api.js` 的 `conversationStream` 用
`wx.request({enableChunked: true})` + `onChunkReceived` 手工拼 UTF-8 并按 `\n\n`
切帧，微信开发者工具对流式支持有限 —— 工具里看着不动不代表坏了，结论以真机为准。

## 搜索

`miniprogram_npm/` 是入库的第三方组件（TDesign），全文搜索必须排除，
否则源码（约 30 个文件）会被上千个文件淹没。
