"""微信登录 + token 会话 + 每用户每日限流（SQLite，单 worker）。

链路：小程序 wx.login → code → /auth/login → 后端 code2session 换 openid
     → 签发随机 token（存 session 表）→ 之后 /chat 带 Bearer token
     → 校验 token 取 openid → 按 openid+day 记额度、超限则拒。

依赖单进程（ADR-0002）：SQLite 计数在单 worker 下即够用。
"""
import os
import secrets
import sqlite3
import threading
from datetime import datetime, date

import requests
from fastapi import HTTPException

from app import config

DB_PATH = os.path.join(config.DATA_DIR, "auth.db")
_lock = threading.Lock()

CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


def _conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    with _conn() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS session ("
            "token TEXT PRIMARY KEY, openid TEXT, created_at TEXT)"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS usage ("
            "openid TEXT, day TEXT, count INTEGER DEFAULT 0, "
            "PRIMARY KEY (openid, day))"
        )
        # 内部 user_id：用户业务数据挂它，不挂 openid（ADR-0007）。
        # openid 是微信这一个渠道的产物，而行程数据会跨渠道长期累积。
        c.execute(
            "CREATE TABLE IF NOT EXISTS user ("
            "id TEXT PRIMARY KEY, created_at TEXT)"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS identity ("
            "provider TEXT NOT NULL, external_id TEXT NOT NULL, "
            "user_id TEXT NOT NULL, created_at TEXT, "
            "PRIMARY KEY (provider, external_id))"
        )


def code2session(code: str) -> str:
    """用 code 换 openid。失败抛 HTTPException。"""
    if not config.WX_APPID or not config.WX_APPSECRET:
        raise HTTPException(500, "服务未配置微信 AppID/AppSecret，无法登录。")
    try:
        resp = requests.get(CODE2SESSION_URL, params={
            "appid": config.WX_APPID,
            "secret": config.WX_APPSECRET,
            "js_code": code,
            "grant_type": "authorization_code",
        }, timeout=10)
        data = resp.json()
    except Exception:
        raise HTTPException(502, "微信登录服务不可用，请稍后重试。")
    openid = data.get("openid")
    if not openid:
        # 微信返回 errcode/errmsg，如 40029 code 无效
        raise HTTPException(401, f"微信登录失败：{data.get('errmsg', '未知错误')}")
    return openid


def login(code: str) -> str:
    """换 openid 并签发 token，返回 token。"""
    openid = code2session(code)
    token = secrets.token_urlsafe(32)
    init_db()
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO session(token, openid, created_at) VALUES (?,?,?)",
            (token, openid, datetime.now().isoformat(timespec="seconds")),
        )
    # 登录时就建号，而不是等他第一次点开行程页——建号动作放在登录这个
    # 本来就要写库的路径上，后续所有业务接口拿 user_id 都是纯读。
    user_id_of("wx", openid)
    return token


def _openid_of(token: str):
    init_db()
    with _conn() as c:
        row = c.execute(
            "SELECT openid FROM session WHERE token=?", (token,)
        ).fetchone()
    return row[0] if row else None


def require_user(authorization: str) -> str:
    """校验 Bearer token，返回 openid。无效抛 401。"""
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "未登录：缺少 token，请重新登录。")
    openid = _openid_of(token)
    if not openid:
        raise HTTPException(401, "登录已失效，请重新登录。")
    return openid


def _bump(key: str, limit: int, over_msg: str):
    """通用日额度计数。key 进 usage 表（不同用途加前缀隔离），limit<=0 表示不限。"""
    if limit <= 0:
        return
    today = date.today().isoformat()
    init_db()
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT count FROM usage WHERE openid=? AND day=?", (key, today)
        ).fetchone()
        used = row[0] if row else 0
        if used >= limit:
            raise HTTPException(429, over_msg)
        c.execute(
            "INSERT INTO usage(openid, day, count) VALUES (?,?,1) "
            "ON CONFLICT(openid, day) DO UPDATE SET count = count + 1",
            (key, today),
        )


def check_and_bump_quota(openid: str):
    """当日提问额度 +1；超过 DAILY_LIMIT 抛 429。DAILY_LIMIT=0 表示不限。"""
    _bump(openid, config.DAILY_LIMIT,
          f"今日提问已达上限（{config.DAILY_LIMIT} 次），请明天再来。")


def check_and_bump_feedback_quota(openid: str):
    """当日报错额度 +1。用 'fb:' 前缀与提问额度隔离，互不挤占。"""
    _bump(f"fb:{openid}", config.FEEDBACK_DAILY_LIMIT,
          f"今日反馈已达上限（{config.FEEDBACK_DAILY_LIMIT} 次），请明天再来。")


def require_user_with_quota(authorization: str) -> str:
    """校验登录 + 扣当日提问额度，返回 openid。供 /chat 系列依赖。"""
    openid = require_user(authorization)
    check_and_bump_quota(openid)
    return openid


def user_id_of(provider: str, external_id: str) -> str:
    """取内部 user_id，没有就建号（首次登录即注册）。

    `_lock` 已经串行化了同进程的并发，这里仍用 `INSERT OR IGNORE` + 回查兜底：
    真正的风险是哪天服务跑成多进程（ADR-0002 的单 worker 前提一旦破掉），
    那时「先查、没有再插」会给同一个用户劈出两个 user_id，行程被切成两半且无从合并。
    """
    init_db()
    now = datetime.now().isoformat(timespec="seconds")
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT user_id FROM identity WHERE provider=? AND external_id=?",
            (provider, external_id),
        ).fetchone()
        if row:
            return row[0]
        uid = secrets.token_hex(8)
        c.execute("INSERT INTO user(id, created_at) VALUES (?,?)", (uid, now))
        c.execute(
            "INSERT OR IGNORE INTO identity(provider, external_id, user_id, created_at) "
            "VALUES (?,?,?,?)", (provider, external_id, uid, now),
        )
        # 并发下别人可能刚插进去，以库里那条为准（自己那行 user 成孤儿，无害）
        return c.execute(
            "SELECT user_id FROM identity WHERE provider=? AND external_id=?",
            (provider, external_id),
        ).fetchone()[0]


def require_app_user(authorization: str) -> str:
    """校验登录，返回内部 user_id。供各产品线的用户数据接口使用，**不扣任何额度**。

    与铁路无关——乘车记录、奖赏钱记录都用它。原名 `require_rail_user`，
    在奖赏钱模块接入时改成现名。
    """
    return user_id_of("wx", require_user(authorization))


def require_admin(authorization: str):
    """校验管理员令牌。Header 形如 'Bearer <token>' 或直接 <token>。

    放在这里而不是 `main.py`，是为了让子包（`rail/` `rewardcash/`）能用——
    从 `main` 反向 import 会成环。
    """
    if not config.ADMIN_TOKEN:
        raise HTTPException(500, "服务未配置 ADMIN_TOKEN，管理接口不可用。")
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token != config.ADMIN_TOKEN:
        raise HTTPException(401, "未授权：ADMIN_TOKEN 不匹配。")


def delete_account(openid: str):
    """注销账号：删身份、内部账号与该 openid 的全部登录 session。返回被删的 user_id。

    个保法的「删除权」（ADR-0007「必须提供删除能力」）。业务数据（乘车记录）
    由调用方先删——本函数只管身份这一层，跨模块的删除顺序见 `rail/api.py`。

    删 session 是关键一步：token 永不过期（ADR-0007 已记下这笔技术债），
    不删的话注销后那串 token 仍能过 `require_user`，而 `user_id_of` 会给它
    新建一个 user_id——用户以为注销了，实际拿着旧 token 悄悄开了个新号。

    **幂等**：查不到身份时什么都不做并返回 None，不抛异常。

    ⚠️ 不删 `usage` 表的日额度计数。那是按 openid+日 的防刷计数，不是用户业务数据；
    删了就等于给「注销再注册」开了一条刷额度的路，而 openid 注销后并不会变。
    """
    init_db()
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT user_id FROM identity WHERE provider=? AND external_id=?",
            ("wx", openid),
        ).fetchone()
        uid = row[0] if row else None
        if uid:
            # 按 user_id 删身份，而不是按 openid：将来同一账号绑了多个渠道
            # （ADR-0007 为「未来 iOS」留的口），注销必须把所有渠道一起断开，
            # 否则会留下指向已删 user 的孤儿身份。
            c.execute("DELETE FROM identity WHERE user_id=?", (uid,))
            c.execute("DELETE FROM user WHERE id=?", (uid,))
        c.execute("DELETE FROM session WHERE openid=?", (openid,))
    return uid


def require_user_with_feedback_quota(authorization: str) -> str:
    """校验登录 + 扣当日报错额度，返回 openid。**不消耗提问次数**——
    不该因为用户愿意反馈就减少他能问的问题。"""
    openid = require_user(authorization)
    check_and_bump_feedback_quota(openid)
    return openid


def require_user_with_rail_quota(authorization: str) -> str:
    """校验登录 + 扣当日铁路查询额度，返回 openid。**不消耗提问次数**——
    时刻表查询与 RAG 问答无关，不该因为记了几趟车就少问几个问题。
    额度存在只为拦「爬全量时刻表」。用 'rail:' 前缀隔离。"""
    openid = require_user(authorization)
    _bump(f"rail:{openid}", config.RAIL_QUERY_DAILY_LIMIT,
          f"今日车次查询已达上限（{config.RAIL_QUERY_DAILY_LIMIT} 次），请明天再来。")
    return openid
