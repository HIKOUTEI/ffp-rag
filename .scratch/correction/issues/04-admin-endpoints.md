# 04 · 管理接口：列队列 / 标记已处理

Status: resolved

## 任务

`main.py` 新增两个走 `_require_admin` 的接口：

- `GET /admin/corrections?status=pending&limit=100` → `{"corrections": [...]}`。
  每条记录里的 `doc_ids` 需**回填当前知识正文**（用 `store.get_doc`），
  让后台能直接内联展示与编辑；已被删除的 id 标记为缺失而非报错。
- `PATCH /admin/corrections/{id}`，body `{"resolution": "..."}` → 置为已处理。
  记录不存在返回 404。

## 验收

- 默认只返回 pending；`status=all` 能看到全部。
- 关联知识已被删除的记录仍能正常列出，不 500。
- `PATCH` 之后该条不再出现在 pending 列表里。

## Comments
