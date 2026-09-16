# 01 · store.search 带出 doc_id，Source 暴露 doc_id

Status: resolved

## 任务

让「这次回答用了库里哪几条知识」能传到客户端。

- `store.search()`：结果字典新增 `doc_id`。正文命中取 chroma 返回的 id；
  别名命中取 `meta["parent_id"]`（别名入库时已写入，见 `add_fragments`）。
  注意现有按正文文本去重、保留最高分的逻辑要一并保留 `doc_id`。
- `search_smart()` 的合并去重同样透传 `doc_id`。
- `schemas.Source` 新增 `doc_id: str = ""`。
- `main.py` 中构造 `Source` 的三处（`/chat`、`/chat/conversation`、两个 stream 的
  `sources` 事件）都带上 `doc_id`。

## 验收

- 调 `/chat/conversation`，返回的每个 source 都有非空 `doc_id`，且该 id 能在
  `GET /admin/docs` 的列表里找到。
- 命中别名的结果，其 `doc_id` 指向正文条目而非 `xxx-alias-N`。

## Comments
