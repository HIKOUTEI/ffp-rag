# 01 · 新增 canonical_url 规范化函数

Status: resolved

## 任务

在合适的模块（建议 `app/ingest_url.py` 或新建 `app/urlutil.py`）新增 `canonical_url(url) -> str`：
- scheme + host 转小写
- 去掉 `#` 片段
- 剔除追踪参数黑名单：`chksm/scene/sn/srcid/from/isappinstalled/utm_source/utm_medium/utm_campaign` 等
- host 为 `mp.weixin.qq.com` 时：仅保留 `__biz/mid/idx/sn`，其余参数全丢

## 验收

- 同一篇公众号文章的不同分享链接（追踪参数不同）→ 归一化结果一致。
- 普通 URL 去掉 `#` 片段与追踪参数后稳定。

## Comments
