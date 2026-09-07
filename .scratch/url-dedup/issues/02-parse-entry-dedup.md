# 02 · parse 入口同步判重

Status: resolved

## 任务

`/admin/parse-url`（`app/main.py`）在起后台线程之前：
- 对 `req.url` 求 `canonical_url`
- 用 `store` 查库：`col.get(where={"$and":[{"url": canonical},{"kind":"doc"}]})`（或封装成 `store.find_ingested_url(canonical)`）
- 命中：同步返回 `already_ingested: true` + 已录入片段的 `source` / `date` / 片段数（`count`），**不发 task、不抓取、不调 AI**
- 未命中：照原流程 `parse_async`

## 依赖

Blocked by: 01

## 验收

- 已录入 URL 变体 → 同步返回 already_ingested，无 task 产生。
- 新 URL → 正常返回 task_id。

## Comments
