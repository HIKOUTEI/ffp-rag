# Spec: URL 判重（相同 URL 不重复录入）

## 背景

管理员通过 URL 摄入管线录入知识：`/admin/parse-url`（抓取网页 + AI 抽取切分，**慢、烧 token**）
→ 人工确认 → `/admin/ingest-parsed`（写入 Chroma）。

现状：URL 只作为每条片段的 `url` metadata 存在 Chroma 里，**没有任何 URL 级判重**。
同一篇文章重复提交会重新抓取、重新调 AI，唯一的兜底是 `find_duplicates` 的
按正文文本相似度（≥0.90）逐片段去重——挡不住「同一篇文章又录一遍」。

## 目标

相同 URL 不重复录入：已录入的文章再次提交时，尽早拦截、不抓取、不调 AI。

## 设计决策（经 grilling 敲定）

1. **规范化 URL（Q1）**：新增 `canonical_url(url)`——scheme+host 转小写 → 去 `#` 片段 →
   剔除追踪参数黑名单（`chksm/scene/sn/srcid/from/isappinstalled/utm_*` 等）；
   host 为 `mp.weixin.qq.com` 时只保留 `__biz/mid/idx/sn`。详见 `docs/adr/0001-url-canonicalization.md`。
2. **拦在 parse 入口（Q2）**：在 `/admin/parse-url` 里、起后台线程之前判重。
3. **查 Chroma + 「录入=真正入库」语义（Q3）**：库里存在该规范化 URL 的 `kind=doc` 片段
   才算已录入；解析过但未入库的可重来。
4. **同步硬拦 + 带回信息（Q4）**：命中直接同步返回（不发 task），响应含 `already_ingested: true`
   及已录入片段的 source / date / 片段数，供前端提示「已于 X 录入，来源 Y，共 N 条」。
5. **存量迁移 + 入库统一存规范化 URL（Q5）**：
   - `add_fragments` 与 `ingest_url` 里给 `f["url"]` 赋值处改存 `canonical_url`。
   - 一次性迁移脚本把 Chroma 现有片段的 `url` 就地规范化重写。
   - 判重用精确 `col.get(where={"url": canonical, "kind": "doc"})`。

## 术语（已写入 CONTEXT.md）

- **规范化 URL / Canonical URL**
- **已录入 / Ingested**

## 明确不做

- 不做完整的公众号文章身份反推（短链跳转、`__biz` 解码等），见 ADR-0001。
- 不拦「解析过但未入库」的 URL——人工拒绝后允许重新解析。

## 验收

- 提交一个已录入文章的 URL 变体（带不同追踪参数）→ parse 入口同步返回 `already_ingested`，
  不产生 task、不发生抓取与 AI 调用。
- 提交未录入的新 URL → 照常走解析流程。
- 迁移脚本跑完后，库内片段 `url` 均为规范化形式。
