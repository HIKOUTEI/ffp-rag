# 02 · corrections 表与读写函数

Status: resolved

## 任务

在 `app/changelog.py`（复用 `changelog.db` 与现有异常静默写法）新增纠错记录的存储层。

建表 `corrections`：
`id` / `question` / `rewritten` / `answer` / `doc_ids`(JSON) / `sources`(JSON) /
`note` / `openid` / `status`(`pending`|`done`) / `resolution` / `created_at` / `resolved_at`。

函数：
- `record_correction(question, rewritten, answer, doc_ids, sources, note, openid) -> int|None`
- `list_corrections(status="pending", limit=100)` — 新→旧
- `resolve_correction(id, resolution) -> bool` — 置 `done` + 写 `resolved_at`

`init_db()` 里一并建表。所有函数沿用现有 `try/except: pass` 容错风格，
**但 `resolve_correction` 需要真实返回成功与否**（后台要据此报 404）。

## 验收

- 新表在已有 `changelog.db` 上能自动建出来，不影响既有两张表。
- `list_corrections("pending")` 不返回已处理的记录；`status=None`/`"all"` 时返回全部。

## Comments
