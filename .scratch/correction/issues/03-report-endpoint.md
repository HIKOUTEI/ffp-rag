# 03 · 上报接口 + 独立日限额

Status: resolved

## 任务

- `auth.py`：新增独立于提问额度的报错限额。复用 `usage` 表，
  key 用 `openid` 加前缀（如 `fb:<openid>`）与提问额度隔离；
  `config` 新增 `FEEDBACK_DAILY_LIMIT`（默认 10，`0` 表示不限），`.env.example` 同步。
  新增 `require_user_with_feedback_quota(authorization) -> openid`。
- `schemas.py`：`CorrectionRequest`（question / rewritten / answer / doc_ids /
  sources / note，除 question 外均可选）。
- `main.py`：`POST /feedback/correction`，验身份+扣报错额度→`changelog.record_correction`→
  返回 `{"ok": True}`。**不扣提问额度**。

## 验收

- 无 token → 401；超过 `FEEDBACK_DAILY_LIMIT` → 429 且提示可读。
- 连续报错若干次后，用户的提问次数不受影响（`/chat` 仍可正常用满原额度）。

## Comments
