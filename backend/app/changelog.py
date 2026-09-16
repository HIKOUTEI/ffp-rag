"""知识变更追踪：单条历史 + 变更日志 + 纠错记录（SQLite）。

- knowledge_history：一条知识被改/删前，把旧版本存一份（可回溯）。
- change_log：整库的增删改流水账。
- corrections：用户报上来的纠错记录，管理员的待办队列（见 ADR-0005）。
容错：任何异常静默忽略，不影响主链路。
"""
import json
import os
import sqlite3
import threading
from datetime import datetime

from app import config

DB_PATH = os.path.join(config.DATA_DIR, "changelog.db")
_lock = threading.Lock()


def _conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    with _conn() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS knowledge_history ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, old_text TEXT, "
            "old_meta TEXT, action TEXT, changed_at TEXT)"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS change_log ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT, target TEXT, "
            "summary TEXT, at TEXT)"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS corrections ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, rewritten TEXT, "
            "answer TEXT, doc_ids TEXT, sources TEXT, note TEXT, openid TEXT, "
            "status TEXT DEFAULT 'pending', resolution TEXT, "
            "created_at TEXT, resolved_at TEXT)"
        )


def record_history(doc_id, old_text, old_meta, action):
    """改/删前保存旧版本。action: 'update' | 'delete'。"""
    try:
        init_db()
        with _lock, _conn() as c:
            c.execute(
                "INSERT INTO knowledge_history(doc_id, old_text, old_meta, action, changed_at) "
                "VALUES (?,?,?,?,?)",
                (doc_id, old_text, json.dumps(old_meta, ensure_ascii=False),
                 action, datetime.now().isoformat(timespec="seconds")),
            )
    except Exception:
        pass


def record_change(action, target, summary):
    """记一条变更流水。action: 'add' | 'update' | 'delete'。"""
    try:
        init_db()
        with _lock, _conn() as c:
            c.execute(
                "INSERT INTO change_log(action, target, summary, at) VALUES (?,?,?,?)",
                (action, target, summary, datetime.now().isoformat(timespec="seconds")),
            )
    except Exception:
        pass


def list_history(doc_id):
    """某条知识的历史版本（新→旧）。"""
    try:
        init_db()
        with _conn() as c:
            rows = c.execute(
                "SELECT old_text, old_meta, action, changed_at FROM knowledge_history "
                "WHERE doc_id=? ORDER BY id DESC", (doc_id,),
            ).fetchall()
        return [{"old_text": r[0], "old_meta": json.loads(r[1] or "{}"),
                 "action": r[2], "changed_at": r[3]} for r in rows]
    except Exception:
        return []


def list_changes(limit=100):
    """全库变更流水（新→旧）。"""
    try:
        init_db()
        with _conn() as c:
            rows = c.execute(
                "SELECT action, target, summary, at FROM change_log "
                "ORDER BY id DESC LIMIT ?", (limit,),
            ).fetchall()
        return [{"action": r[0], "target": r[1], "summary": r[2], "at": r[3]} for r in rows]
    except Exception:
        return []


# ---- 纠错记录 ----

def record_correction(question, rewritten, answer, doc_ids, sources, note, openid):
    """存一条用户报错。返回记录 id，失败返回 None（不影响用户侧体验）。"""
    try:
        init_db()
        with _lock, _conn() as c:
            cur = c.execute(
                "INSERT INTO corrections(question, rewritten, answer, doc_ids, sources, "
                "note, openid, status, created_at) VALUES (?,?,?,?,?,?,?,'pending',?)",
                (question, rewritten, answer,
                 json.dumps(doc_ids, ensure_ascii=False),
                 json.dumps(sources, ensure_ascii=False),
                 note, openid, datetime.now().isoformat(timespec="seconds")),
            )
            return cur.lastrowid
    except Exception:
        return None


def list_corrections(status="pending", limit=100):
    """纠错队列（新→旧）。status 传 None 或 'all' 时返回全部。"""
    try:
        init_db()
        sql = ("SELECT id, question, rewritten, answer, doc_ids, sources, note, openid, "
               "status, resolution, created_at, resolved_at FROM corrections")
        params = []
        if status and status != "all":
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with _conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [{
            "id": r[0], "question": r[1], "rewritten": r[2], "answer": r[3],
            "doc_ids": json.loads(r[4] or "[]"), "sources": json.loads(r[5] or "[]"),
            "note": r[6], "openid": r[7], "status": r[8], "resolution": r[9],
            "created_at": r[10], "resolved_at": r[11],
        } for r in rows]
    except Exception:
        return []


def resolve_correction(correction_id, resolution):
    """标记为已处理。返回是否命中（供接口报 404），异常按未命中处理。"""
    try:
        init_db()
        with _lock, _conn() as c:
            cur = c.execute(
                "UPDATE corrections SET status='done', resolution=?, resolved_at=? "
                "WHERE id=? AND status='pending'",
                (resolution, datetime.now().isoformat(timespec="seconds"), correction_id),
            )
            return cur.rowcount > 0
    except Exception:
        return False
