# 03 · 入库统一存规范化 URL + 存量迁移脚本

Status: resolved

## 任务

1. **入库统一存规范化 URL**：
   - `ingest_url._run_parse` 里 `f["url"] = url` 改为 `f["url"] = canonical_url(url)`。
   - `store.add_fragments` 写 metadata 时对 `url` 再兜底 `canonical_url`（防御性）。
2. **一次性迁移脚本** `backend/scripts/canonicalize_urls.py`（仿 `rebuild_aliases.py`）：
   - 遍历 Chroma 所有片段，对非空 `url` 求 `canonical_url`，有变化的 `col.update` 就地重写 metadata。
   - 打印处理条数 / 变更条数。

## 依赖

Blocked by: 01

## 验收

- 迁移脚本跑完，库内所有片段 `url` 均为规范化形式（幂等：再跑一次变更数为 0）。
- 之后新入库片段存的就是规范化 URL，02 的精确 `where` 判重稳定命中。

## Comments
