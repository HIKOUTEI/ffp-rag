# 常旅客助手 · 微信小程序

ffp-rag 的 C 端问答前端（原生小程序），与网页 React、后端共享同一套 API。

## 运行

1. 用**微信开发者工具**打开本目录 `miniprogram/`。
2. `project.config.json` 里的 `appid` 目前是占位 `touristappid`，替换成你的 AppID。
3. 后端本地起服务：`cd ../backend && uvicorn app.main:app --reload`。
4. 开发者工具 → 详情 → 本地设置 → 勾选**「不校验合法域名」**（本地 http 联调）。
5. 后端地址在 `config.js` 的 `BASE_URL`，云部署后改这里即可。

## 结构

- `pages/chat/` 聊天页：多轮对话、流式打字机、来源标签、本地会话持久化、首屏热门问题。
- `pages/about/` 关于页：简介 + 收录范围 + 免责声明。
- `api.js` SSE over `wx.request(enableChunked)` 客户端 + 热门问题接口。
- `md.js` 极简 Markdown（**加粗** + 列表）→ rich-text 渲染。
- `config.js` `BASE_URL` 与域名中文名常量。

## 已知限制

- **流式（打字机）只能在真机验证**：`enableChunked` 在开发者工具支持有限。真机预览需
  合法 https 域名（云部署后配置，或用内网穿透临时 https 地址）。
- 来源标签**纯展示不跳转**：小程序 `web-view` 有业务域名白名单限制，公众号等第三方
  域名无法登记。
