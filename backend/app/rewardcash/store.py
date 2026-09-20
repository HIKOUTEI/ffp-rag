"""`rewardcash.db` —— 规则集 + 用户的月结／签账／设置。

四张表放一个库：规则集虽是全局只读数据，但它**不会被批量替换**（与 `rail.db`
每周原子替换不同），和用户数据同库没有被冲掉的风险。

⚠️ 本模块最容易写错的地方在 `monthly_entry`：它同时存**流量**（`earned_json`，
当月赚取，可跨月加总）与**存量**（`balance` / `expiring_*`，期末快照，
**不可加总**，只取最新一条）。把 13 个月的余额加起来会得到一个毫无意义、
但看起来很像对的大数。读取侧务必分开处理，见 `summary.py`。
"""
import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime

from app import config

DB_PATH = os.path.join(config.DATA_DIR, "rewardcash.db")
_lock = threading.Lock()

SCHEMA = """
-- 规则集：整份 JSON 存一行，append-only 版本。
-- 不做规范化（见 issue 01）：规则仅 6 条、单人维护、永远整份读出整份下发，
-- 拆三张表只会多一套 CRUD 表单，而约束本来就全在 pydantic 里。
CREATE TABLE IF NOT EXISTS ruleset (
  version    INTEGER PRIMARY KEY AUTOINCREMENT,
  json       TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  note       TEXT
);

-- 月结记录：一月一条，照 Reward+ App 抄（ADR-0010）。
CREATE TABLE IF NOT EXISTS monthly_entry (
  id          TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL,        -- 内部 user_id（ADR-0007），不是 openid
  month       TEXT NOT NULL,        -- 'YYYY-MM'
  -- ── 流量：当月赚取，可跨月加总 ──
  earned_json TEXT NOT NULL,        -- {"<reward_category>": <RC>}
  -- ── 存量：期末快照，不可加总，只取最新 ──
  balance         REAL,
  expiring_amount REAL,
  expiring_date   TEXT,             -- YYYY-MM-DD
  -- 数据在 Reward+ 上的时点，**不等于** updated_at（用户可能今天补抄上月的数）
  snapshot_at TEXT,
  created_at  TEXT,
  updated_at  TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_month_user ON monthly_entry(user_id, month);

-- 签账记录：可选的逐笔。唯一不可替代的用途是月中推算门槛进度——
-- 月结次月才抄，那时门槛周期已结束（ADR-0010）。
CREATE TABLE IF NOT EXISTS spend_entry (
  id         TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL,
  spend_date TEXT NOT NULL,         -- YYYY-MM-DD
  amount     REAL NOT NULL,         -- 原币金额
  currency   TEXT NOT NULL,
  amount_hkd REAL NOT NULL,         -- 门槛与签账上限一律以港币计
  region     TEXT NOT NULL,
  merchant_category TEXT NOT NULL,
  channel    TEXT NOT NULL,
  -- 「消费发生在内地、但终端结算成了港币」是合法组合，且正是那个同时丢掉
  -- 扫码 +2% 和 Travel Guru +6% 的 DCC 陷阱。用 currency='HKD' 表达会丢掉
  -- 「这笔发生在内地」的信息，故单独一列。
  settled_hkd INTEGER NOT NULL DEFAULT 0,
  card       TEXT,                  -- 可选标卡，'pulse' | 自由文本
  note       TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_spend_user ON spend_entry(user_id, spend_date);

-- 用户侧的规则状态。没有它，上限进度算出来会误导：
-- 显示「还剩 HK$35,050 可刷」，而真相可能是没登记、一分没在计。
CREATE TABLE IF NOT EXISTS user_setting (
  user_id  TEXT PRIMARY KEY,
  -- {"<rule_id>": "YYYY-MM-DD" | null}。存**日期**不是布尔：登记日决定从哪天起计。
  -- null = 确认未登记；key 不存在 = 没问过。三态，别压成两态。
  enrolled_json TEXT,
  membership_year_start TEXT,       -- Travel Guru 会籍年起算日
  travel_guru_tier TEXT,            -- 'go' | 'ging' | 'guru'
  updated_at TEXT
);
"""


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as c:
        c.executescript(SCHEMA)


def _now():
    return datetime.now().isoformat(timespec="seconds")


# ────────────────────────────── 规则集 ──────────────────────────────

def latest_ruleset():
    """返回 (version, data) —— 库里没有任何版本时返回 (0, None)。"""
    init_db()
    with _conn() as c:
        row = c.execute(
            "SELECT version, json FROM ruleset ORDER BY version DESC LIMIT 1"
        ).fetchone()
    if not row:
        return 0, None
    return row["version"], json.loads(row["json"])


def put_ruleset(data, note=None):
    """写入新版本，返回新 version。**调用方必须先过 pydantic 校验**。

    append-only：旧版本保留，便于对照「哪一版起算错了」。
    """
    init_db()
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO ruleset(json, updated_at, note) VALUES (?,?,?)",
            (json.dumps(data, ensure_ascii=False), _now(), note),
        )
    return cur.lastrowid


def list_ruleset_versions(limit=50):
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT version, updated_at, note FROM ruleset "
            "ORDER BY version DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_ruleset_version(version):
    init_db()
    with _conn() as c:
        row = c.execute("SELECT json FROM ruleset WHERE version=?",
                        (version,)).fetchone()
    return json.loads(row["json"]) if row else None


# ───────────────────────────── 月结记录 ─────────────────────────────

def _row_to_month(r):
    return {
        "month": r["month"],
        # 分成两个嵌套对象而不是平铺：流量与存量在类型上就不该混在一起，
        # 否则任何「近 N 个月汇总」的代码都会顺手把余额也加起来。
        "flow": {"earned": json.loads(r["earned_json"])},
        "stock": {
            "balance": r["balance"],
            "expiring": {"amount": r["expiring_amount"], "date": r["expiring_date"]},
            "snapshot_at": r["snapshot_at"],
        },
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def put_month(user_id, month, earned, balance=None,
              expiring_amount=None, expiring_date=None, snapshot_at=None):
    """幂等 upsert。用户会反复回来改同一个月（抄错、或月中先抄一次）。

    `created_at` 保持首次写入的值，只刷 `updated_at`。
    """
    init_db()
    now = _now()
    payload = json.dumps(earned, ensure_ascii=False)
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO monthly_entry(id, user_id, month, earned_json, balance,"
            " expiring_amount, expiring_date, snapshot_at, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(user_id, month) DO UPDATE SET"
            "   earned_json=excluded.earned_json,"
            "   balance=excluded.balance,"
            "   expiring_amount=excluded.expiring_amount,"
            "   expiring_date=excluded.expiring_date,"
            "   snapshot_at=excluded.snapshot_at,"
            "   updated_at=excluded.updated_at",
            (secrets.token_hex(8), user_id, month, payload, balance,
             expiring_amount, expiring_date, snapshot_at, now, now),
        )
    return get_month(user_id, month)


def get_month(user_id, month):
    init_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM monthly_entry WHERE user_id=? AND month=?",
                        (user_id, month)).fetchone()
    return _row_to_month(row) if row else None


def list_months(user_id, limit=60):
    """按月倒序。`month` 是 'YYYY-MM'，字符串序即时间序。"""
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM monthly_entry WHERE user_id=? ORDER BY month DESC LIMIT ?",
            (user_id, limit)).fetchall()
    return [_row_to_month(r) for r in rows]


def delete_month(user_id, month):
    init_db()
    with _lock, _conn() as c:
        cur = c.execute("DELETE FROM monthly_entry WHERE user_id=? AND month=?",
                        (user_id, month))
    return cur.rowcount > 0


# ───────────────────────────── 签账记录 ─────────────────────────────

_SPEND_COLS = ("spend_date", "amount", "currency", "amount_hkd", "region",
               "merchant_category", "channel", "settled_hkd", "card", "note")


def _row_to_spend(r):
    d = {k: r[k] for k in _SPEND_COLS}
    d["settled_hkd"] = bool(r["settled_hkd"])
    d["id"] = r["id"]
    return d


def create_spend(user_id, **f):
    init_db()
    sid = secrets.token_hex(8)
    now = _now()
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO spend_entry(id, user_id, spend_date, amount, currency,"
            " amount_hkd, region, merchant_category, channel, settled_hkd, card,"
            " note, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, user_id, f["spend_date"], f["amount"], f["currency"],
             f["amount_hkd"], f["region"], f["merchant_category"], f["channel"],
             int(f.get("settled_hkd") or 0), f.get("card"), f.get("note"), now, now),
        )
    return sid


def list_spends(user_id, date_from=None, date_to=None, limit=200):
    init_db()
    sql = "SELECT * FROM spend_entry WHERE user_id=?"
    args = [user_id]
    if date_from:
        sql += " AND spend_date >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND spend_date <= ?"
        args.append(date_to)
    sql += " ORDER BY spend_date DESC, created_at DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        rows = c.execute(sql, args).fetchall()
    return [_row_to_spend(r) for r in rows]


def update_spend(user_id, sid, fields):
    """改 `fields` 给出的列，返回是否命中。改别人的记录命中 0 行 → 调用方回 404。"""
    if not fields:
        init_db()
        with _conn() as c:
            row = c.execute("SELECT 1 FROM spend_entry WHERE id=? AND user_id=?",
                            (sid, user_id)).fetchone()
        return row is not None
    init_db()
    sets = ", ".join(f"{k}=?" for k in fields)
    with _lock, _conn() as c:
        cur = c.execute(
            f"UPDATE spend_entry SET {sets}, updated_at=? WHERE id=? AND user_id=?",
            (*fields.values(), _now(), sid, user_id))
    return cur.rowcount > 0


def delete_spend(user_id, sid):
    init_db()
    with _lock, _conn() as c:
        cur = c.execute("DELETE FROM spend_entry WHERE id=? AND user_id=?",
                        (sid, user_id))
    return cur.rowcount > 0


# ────────────────────────────── 设置 ──────────────────────────────

def get_settings(user_id):
    init_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM user_setting WHERE user_id=?",
                        (user_id,)).fetchone()
    if not row:
        return {"enrolled": {}, "membership_year_start": None, "travel_guru_tier": None}
    return {
        "enrolled": json.loads(row["enrolled_json"] or "{}"),
        "membership_year_start": row["membership_year_start"],
        "travel_guru_tier": row["travel_guru_tier"],
    }


def put_settings(user_id, enrolled, membership_year_start, travel_guru_tier):
    init_db()
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO user_setting(user_id, enrolled_json, membership_year_start,"
            " travel_guru_tier, updated_at) VALUES (?,?,?,?,?)"
            " ON CONFLICT(user_id) DO UPDATE SET"
            "   enrolled_json=excluded.enrolled_json,"
            "   membership_year_start=excluded.membership_year_start,"
            "   travel_guru_tier=excluded.travel_guru_tier,"
            "   updated_at=excluded.updated_at",
            (user_id, json.dumps(enrolled, ensure_ascii=False),
             membership_year_start, travel_guru_tier, _now()),
        )
    return get_settings(user_id)


# ───────────────────────── 注销时的数据清理 ─────────────────────────

def delete_all_for(user_id):
    """删某用户在本模块的全部数据。个保法的删除权——注销时必须连这三张表一起清。

    `ruleset` 是全局数据，不属于任何用户，不动。
    """
    init_db()
    with _lock, _conn() as c:
        n1 = c.execute("DELETE FROM monthly_entry WHERE user_id=?", (user_id,)).rowcount
        n2 = c.execute("DELETE FROM spend_entry WHERE user_id=?", (user_id,)).rowcount
        n3 = c.execute("DELETE FROM user_setting WHERE user_id=?", (user_id,)).rowcount
    return {"months": n1, "spends": n2, "settings": n3}
