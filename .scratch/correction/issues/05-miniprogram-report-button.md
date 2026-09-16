# 05 · 小程序「👎 报错」入口

Status: resolved

## 任务

- `api.js`：新增 `reportCorrection(payload)`。
- `pages/chat/chat.js`：
  - 接收 SSE `sources` 事件时，把 sources（含 `doc_id`）**挂到该条 AI 消息上**
    （目前消息只存 `role/content/status`，sources 被丢弃了）。
  - 新增 `onReport(e)`：`wx.showModal` 带 `editable: true` 收「哪里不对？（选填）」，
    确认后调接口；成功 toast「已收到，感谢反馈」，并把该条消息标记 `reported: true`。
  - 消息本就写入 `STORE_KEY`，`reported` 标记与 sources 随之自然持久化。
- `chat.wxml` / `chat.wxss`：每条 AI 回答下方（来源旁）加「👎 报错」，
  `reported` 时置灰显示「已反馈」且不可点。仅对已完成（非流式进行中）的回答显示。

## 验收

- 回答结束后按钮出现；点击弹输入框；留空也能提交。
- 提交成功后按钮变「已反馈」置灰；杀掉小程序重进，该标记仍在。
- 429/401 时给出可读提示而非静默失败。

## Comments
