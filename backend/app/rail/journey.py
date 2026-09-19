"""`journey.db` —— 用户的乘车记录。

⚠️ **刻意独立于 `rail.db`**。`rail.db` 每周被整库原子替换（issue 01），
用户数据放进去会被周同步冲掉。参考数据可丢弃可重建，乘车记录不可重建。

记录只存「车次号 + seq」这种弱引用，不建外键到 `rail.db`：
车次会停运、时刻表会改点，而记录必须在车次从 `rail.db` 消失之后仍然可读。
渲染时回查 `rail.db` 补站名/时刻/里程，查不到就标 `stale`，不报错。
"""
import os
import secrets
import sqlite3
import threading
from datetime import datetime

from app import config

DB_PATH = os.path.join(config.DATA_DIR, "journey.db")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS journey (
  id           TEXT PRIMARY KEY,
  user_id      TEXT NOT NULL,       -- 内部 user_id（ADR-0007），不是 openid
  train_number TEXT NOT NULL,       -- 完整车次号，如 K551/K554
  ride_date    TEXT NOT NULL,       -- YYYY-MM-DD，用户填的乘车日期
  -- 上/下车站在该车次中的 stop_sequence。手填历史记录（source='manual'）时为空。
  -- 存 seq 而不是站名：同一车次可能两次经停同名站（环线、折返），seq 才能唯一定位。
  from_seq     INTEGER,
  to_seq       INTEGER,
  -- 站名冗余存一份：手填记录只有站名没有 seq；自动填充的记录则靠它在车次
  -- 从 rail.db 消失后仍能显示「我坐过哪到哪」。
  from_station TEXT,
  to_station   TEXT,
  note         TEXT,
  gtfs_version TEXT,                -- 录入时的运行图版本，指向快照（issue 02）
  source       TEXT NOT NULL,       -- 'timetable' 自动填充 | 'manual' 手填历史
  created_at   TEXT,
  updated_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_journey_user ON journey(user_id, ride_date DESC);
"""


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as c:
        c.executescript(SCHEMA)


def create(user_id, **f):
    init_db()
    jid = secrets.token_hex(8)
    now = datetime.now().isoformat(timespec="seconds")
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO journey(id, user_id, train_number, ride_date, from_seq, to_seq,"
            " from_station, to_station, note, gtfs_version, source, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (jid, user_id, f["train_number"], f["ride_date"],
             f.get("from_seq"), f.get("to_seq"),
             f.get("from_station"), f.get("to_station"), f.get("note"),
             f.get("gtfs_version"), f["source"], now, now),
        )
    return jid


def get(user_id, jid):
    """按 id 取单条。**必须带 user_id 条件**——不带就是越权读。"""
    init_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM journey WHERE id=? AND user_id=?",
                        (jid, user_id)).fetchone()
    return dict(row) if row else None


def list_for(user_id, limit=50, offset=0):
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM journey WHERE user_id=? "
            "ORDER BY ride_date DESC, created_at DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset)).fetchall()
    return [dict(r) for r in rows]


def update(user_id, jid, fields):
    """改 `fields` 里给出的列，返回是否命中。改别人的记录命中 0 行。"""
    if not fields:
        return get(user_id, jid) is not None
    init_db()
    sets = ", ".join(f"{k}=?" for k in fields)
    with _lock, _conn() as c:
        cur = c.execute(
            f"UPDATE journey SET {sets}, updated_at=? WHERE id=? AND user_id=?",
            (*fields.values(), datetime.now().isoformat(timespec="seconds"),
             jid, user_id))
    return cur.rowcount > 0


def delete(user_id, jid):
    init_db()
    with _lock, _conn() as c:
        cur = c.execute("DELETE FROM journey WHERE id=? AND user_id=?", (jid, user_id))
    return cur.rowcount > 0


def delete_all(user_id):
    """清空某用户全部记录。个保法要求用户能一键删除自己的数据。"""
    init_db()
    with _lock, _conn() as c:
        cur = c.execute("DELETE FROM journey WHERE user_id=?", (user_id,))
    return cur.rowcount
