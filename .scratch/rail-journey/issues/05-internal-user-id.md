# 05 · 内部 user_id 身份层

Status: done

## 任务

在 `app/auth.py` 引入内部 `user_id`，让用户业务数据不再直接绑 `openid`。
详见 `docs/adr/0007-server-side-user-data.md`。

### 新表（`auth.db`）

```
user(
  id TEXT PRIMARY KEY,        -- 内部 user_id，secrets.token_hex(8)
  created_at TEXT
)

identity(
  provider TEXT NOT NULL,     -- 现在只有 'wx'
  external_id TEXT NOT NULL,  -- openid
  user_id TEXT NOT NULL,
  created_at TEXT,
  PRIMARY KEY (provider, external_id)
)
```

### 函数

- `user_id_of(provider, external_id) -> str` — 查不到则**建号并返回**（首次登录即注册）。
- `require_rail_user(authorization) -> str` — 校验 Bearer token → openid → user_id。
  **不扣提问额度**。

`login()` 里顺带确保 `identity` 行存在，避免首次调 `/rail` 才建号。

## 为什么不直接用 openid

`CONTEXT.md` 首行写明本项目服务"网页 React、微信小程序、**未来 iOS**"。
iOS 原生端拿不到 openid。行程是会长期累积、用户会心疼的数据，
等做 iOS 时再迁移，意味着改所有历史行程的外键。现在加这层的成本是一张两列表。

## 注意：现有 session 表的既有问题

`session(token, openid, created_at)` 目前 **token 永不过期、无 openid 索引**，
每次 `relogin` 插一行新 token。本 issue **不修**这个问题（超出范围），
但要意识到：openid 本身是稳定的，所以换手机/重装小程序后数据能正确找回。

## 验收

- 同一 openid 多次登录拿到**同一个** `user_id`。
- 新 openid 首次访问 `/rail` 自动建号。
- 两张新表在已有 `auth.db` 上自动建出，不影响 `session` / `usage`。
- 调 `/rail` 接口不影响 `/chat` 的当日提问额度。

## Comments

### 2026-09-17 实现完成

`backend/app/auth.py`：`user` / `identity` 两张表进 `init_db()`，
新增 `user_id_of(provider, external_id)` 与 `require_rail_user(authorization)`，
`login()` 末尾调 `user_id_of` 建号。

拿真实 `backend/auth.db` 复制一份做升级验证，实跑：

```
升级后表: identity, session, usage, user；session/usage 行数不变
同一 openid 两次 → 同一个 user_id ✓
不同 openid → 不同 user_id ✓
12 线程并发首次建号 → 只产出 1 个 user_id、identity 只 1 行 ✓
新 openid 首次 require_rail_user 自动建号 ✓
无效 token → 401 ✓
```

**建号放在 `login()` 而不是等首次访问 `/rail`**：登录本来就要写库，
建号搭在这条路径上，之后所有业务接口取 `user_id` 都是纯读。
`require_rail_user` 仍保留建号能力，兜住本次改动之前就已登录、库里没有 identity 行的老用户。

`user_id_of` 用 `INSERT OR IGNORE` + 回查而非「先查没有再插」。同进程有 `_lock` 串行化，
这么写是防 ADR-0002 的单 worker 前提哪天破掉——多进程下先查后插会给同一用户
劈出两个 user_id，行程切成两半且无从合并。
