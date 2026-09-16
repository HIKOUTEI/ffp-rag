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
from fastapi import HTTPException, Header

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


def require_user_with_feedback_quota(authorization: str) -> str:
    """校验登录 + 扣当日报错额度，返回 openid。**不消耗提问次数**——
    不该因为用户愿意反馈就减少他能问的问题。"""
    openid = require_user(authorization)
    check_and_bump_feedback_quota(openid)
    return openid
