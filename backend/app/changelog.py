"""知识变更追踪：单条历史 + 变更日志（SQLite）。

- knowledge_history：一条知识被改/删前，把旧版本存一份（可回溯）。
- change_log：整库的增删改流水账。
容错：任何异常静默忽略，不影响主链路。
"""
import json
import os
import sqlite3
import threading
from datetime import datetime

from app import config

DB_PATH = os.path.join(config.BACKEND_DIR, "changelog.db")
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
