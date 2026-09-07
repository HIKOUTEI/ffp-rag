# Spec: 微信小程序前端 + 后端多轮流式/热门榜

## 目标

为 ffp-rag 新增微信小程序前端（纯 C 端问答），与网页 React、未来 iOS 共享同一后端。
配套两项后端增强：多轮流式接口、提问记录与热门榜。

## 后端改动

### 1. `POST /chat/conversation/stream`（多轮 + 追问改写 + SSE 流式）
- 请求体同 `ConversationRequest`（`messages`, `top_k` 默认 6）。
- 流程：`rewrite_query(history, latest)` → `store.search(rewritten, top_k)` →
  `generate_with_history` 的流式版本。
- SSE 事件序列：`event: rewritten`（改写后问题）→ `event: sources`（来源列表）→
  多个 `event: delta`（`{text}`）→ `event: done`。
- 复用现有 `rewrite_query` / `generate_with_history`；需在 `rag.py` 加
  `generate_with_history_stream`（与非流式版同逻辑、`stream=True`）。

### 2. 提问记录 + 热门榜（SQLite）
- 新增 `app/templates.py`：10 条规范问题模板（航司4 / 信用卡3 / 酒店3），
  含 `id`、`text`、`domain`。
- 新增 `app/popular.py`：
  - SQLite 一张表 `template_hits(template_id TEXT PRIMARY KEY, question_text TEXT, count INTEGER)`，
    库文件放 `backend/popular.db`。启动时把模板灌入（count 缺省 0）。
  - `record(question)`：用 `rag.embed` 把 question 归到最近模板（cosine 相似度 ≥ **0.80**
    才 `count += 1`；低于阈值不计入）。模板向量启动时预计算并缓存在内存。
  - `top(n)`：按 count 倒序取 n 条；全 0 时按模板预设顺序返回。
- 在 `/chat/conversation/stream`（及 `/chat/conversation`）命中后调用 `record(latest)`
  （用原始最新问题，非改写；异步/容错，失败不影响问答）。
- 新增 `GET /popular-questions?n=4` → `{questions: [{id, text, domain}]}`。

## 小程序（新目录 `miniprogram/`，原生开发）

- **技术**：原生微信小程序（`.wxml`/`.wxss`/`.js`），无框架。AppID 占位 `touristappid`。
- **风格**：浅色打底 + 旅行蓝主色；用户气泡主色、AI 气泡浅灰。
- **`baseURL`** 抽成 `config.js` 常量；本地用开发者工具「不校验合法域名」联调。

### 页面 1：聊天页（`pages/chat`）
- 多轮对话，消息气泡列表 + 底部输入框。
- 流式打字机：`wx.request` + `enableChunked: true`，`onChunkReceived` 收 `ArrayBuffer`，
  自写 SSE 分帧解析器（按 `\n\n` 切帧，解析 `event:`/`data:`）。
- 每条 AI 答案下显示来源标签（`domain` 中文名 + `source`），纯展示不跳转。
- 答案用 Markdown 渲染（后端输出含 `**加粗**` 与 `-` 列表）——用轻量解析或
  towxml 之类；第一版可先做加粗与列表的极简渲染。
- 当前单会话持久化 `wx.setStorageSync`，进入自动恢复；顶部「新对话」清空。
- 首屏空状态：拉 `GET /popular-questions?n=4`，展示可点气泡，点击直接发送。
- 顶部/首条欢迎气泡含简短免责声明。

### 页面 2：关于页（`pages/about`）
- 一句话简介 + 覆盖范围清单（国航/东航 · 美国运通/招行/联名卡 · 希尔顿/万豪）
  + 免责声明。写死，不调 `/health`。

## 明确不做
小程序管理摄入、历史会话列表、来源跳转、登录/多用户、云部署（后续单独做）。

## 归类阈值
cosine 相似度 ≥ 0.80 计入热门榜，低于不计。跑通后再调。
